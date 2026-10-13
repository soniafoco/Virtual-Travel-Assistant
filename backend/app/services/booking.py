"""Prenotazioni: dalla proposta del planner al salvataggio nel database.

La proposta non tocca le disponibilita'. La conferma le scala tutte insieme (posti del volo, camere,
posti delle attivita') in una transazione: se anche una sola riga non e' piu' disponibile non cambia nulla.
L'annullamento di una prenotazione confermata le ripristina. Nessuna di queste funzioni fa commit:
lo fa chi le chiama (cosi' la richiesta resta atomica).
"""

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.models import (
    ActivityAvailability,
    Booking,
    BookingActivity,
    BookingFlight,
    BookingRoom,
    Flight,
    RoomAvailability,
)
from app.schemas.itinerary import (
    ActivityDay,
    ActivityPick,
    CostBreakdown,
    FlightLeg,
    HotelStay,
    Itinerary,
    RoomNight,
    RoomStay,
)

logger = logging.getLogger(__name__)


class BookingError(Exception):
    """Una richiesta di prenotazione non valida o non piu' eseguibile; il messaggio e' per l'utente."""

def same_trip(old: Booking, itinerary: Itinerary) -> bool:
    """True se la proposta salvata riguarda esattamente gli stessi voli, camere/notti e attivita'/giorni."""
    flights = {(f.direction, f.flight_id) for f in old.flights}
    rooms = {r.room_availability_id for r in old.rooms}
    activities = {a.activity_availability_id for a in old.activities}
    return (
        flights == {("out", itinerary.flight_out.flight_id), ("return", itinerary.flight_return.flight_id)}
        and rooms == {night.availability_id for room in itinerary.hotel.rooms for night in room.nights}
        and activities == {day.activity.availability_id for day in itinerary.days if day.activity}
        and old.travelers == itinerary.travelers
    )

def create_proposal(session: Session, user_id: int, conversation_id: int | None, itinerary: Itinerary) -> Booking:
    """Salva un itinerario come Booking 'proposed': una riga in bookings e le righe figlie (voli, camere, attivita').

    NON tocca le disponibilita': le scala solo la conferma. Le altre proposte aperte restano
    in sospeso: l'utente puo' averne piu' di una, anche nella stessa conversazione.
    Fa flush ma non commit: lo fa il chiamante.
    """
    if conversation_id is not None:
        # se lo stesso itinerario e' gia' stato proposto (es. l'agente richiama save_proposal prima di confermare)
        # non si crea un duplicato: si riusa la proposta aperta
        existing = session.scalars(
            select(Booking).where(Booking.conversation_id == conversation_id, Booking.user_id == user_id, Booking.status == "proposed")
        ).all()
        for old in existing:
            if same_trip(old, itinerary):
                return old

    booking = Booking(
        user_id=user_id, conversation_id=conversation_id, status="proposed",
        label=itinerary.label, country=itinerary.country, city=itinerary.city, hotel_id=itinerary.hotel.hotel_id,
        travelers=itinerary.travelers, nights=itinerary.nights,
        departure_date=itinerary.departure_date, return_date=itinerary.return_date,
        total_cost=itinerary.costs.total,
    )
    booking.flights = [
        BookingFlight(flight_id=itinerary.flight_out.flight_id, direction="out", price_per_person=itinerary.flight_out.price_per_person),
        BookingFlight(flight_id=itinerary.flight_return.flight_id, direction="return", price_per_person=itinerary.flight_return.price_per_person),
    ]
    booking.rooms = [
        BookingRoom(room_availability_id=night.availability_id, price=night.price)
        for room in itinerary.hotel.rooms for night in room.nights
    ]
    booking.activities = [
        BookingActivity(
            activity_availability_id=day.activity.availability_id,
            price_per_person=day.activity.price_per_person, affinity=day.activity.affinity,
        )
        for day in itinerary.days if day.activity is not None
    ]
    session.add(booking)
    session.flush()  # assegna gli id; il commit spetta a chi chiama (cosi' la richiesta e' atomica)
    logger.info("Proposta %s salvata: utente %s, %s, %s persone, %s euro", booking.id, user_id, itinerary.city, itinerary.travelers, itinerary.costs.total)
    return booking

def to_leg(leg: BookingFlight) -> FlightLeg:
    flight = leg.flight
    return FlightLeg(
        flight_id=flight.id, origin=flight.origin_airport, destination=flight.destination_airport,
        departure=flight.departure, arrival=flight.arrival, price_per_person=float(leg.price_per_person),
    )

def itinerary_of(booking: Booking) -> Itinerary:
    """Ricostruisce l'Itinerary di una prenotazione dalle righe del database (bookings + tabelle figlie)."""
    flights = {leg.direction: to_leg(leg) for leg in booking.flights}

    # le camere: una RoomStay per camera, con le sue notti (le righe sono gia' in ordine di id)
    stays: dict[int, RoomStay] = {}
    for row in booking.rooms:
        availability = row.room_availability
        room = availability.room
        if room.id not in stays:
            stays[room.id] = RoomStay(room_id=room.id, name=room.name, capacity=room.capacity, nights=[])
        stays[room.id].nights.append(
            RoomNight(availability_id=availability.id, night=availability.night, price=float(row.price))
        )

    # un'attivita' per giorno; i giorni senza attivita' sono liberi
    picks = {}
    for row in booking.activities:
        slot = row.activity_availability
        picks[slot.day] = ActivityPick(
            availability_id=slot.id, activity_id=slot.activity.id, name=slot.activity.name,
            category=slot.activity.category, price_per_person=float(row.price_per_person), affinity=row.affinity,
        )
    days = []
    for i in range(booking.nights):
        day = booking.departure_date + timedelta(days=i)
        days.append(ActivityDay(day=day, activity=picks.get(day)))

    people = booking.travelers
    flights_cost = sum(leg.price_per_person for leg in flights.values()) * people
    hotel_cost = sum(night.price for stay in stays.values() for night in stay.nights)
    activities_cost = sum(pick.price_per_person for pick in picks.values()) * people
    return Itinerary(
        label=booking.label, country=booking.country, city=booking.city, travelers=people, nights=booking.nights,
        departure_date=booking.departure_date, return_date=booking.return_date,
        flight_out=flights["out"], flight_return=flights["return"],
        hotel=HotelStay(
            hotel_id=booking.hotel.id, name=booking.hotel.name, stars=booking.hotel.stars,
            rooms=list(stays.values()),
        ),
        days=days,
        costs=CostBreakdown(
            flights=round(flights_cost, 2), hotel=round(hotel_cost, 2), activities=round(activities_cost, 2),
            total=float(booking.total_cost),
        ),
        affinity=round(sum(pick.affinity for pick in picks.values()), 4),
        free_days=sum(1 for day in days if day.activity is None),
    )

def get_booking(session: Session, booking_id: int, user_id: int) -> Booking:
    """La prenotazione dell'utente, o BookingError (anche se esiste ma e' di un altro: non si distingue)."""
    booking = session.get(Booking, booking_id)
    if booking is None or booking.user_id != user_id:
        raise BookingError(f"Non trovo la prenotazione {booking_id}.")
    return booking

def confirm_booking(session: Session, booking_id: int, user_id: int) -> Booking:
    """Proposta -> confermata: scala la disponibilita' di volo (andata e ritorno), camere e attivita'.

    Ogni scalatura e' un UPDATE condizionato (`... WHERE posti >= n`, camera ancora libera): se non
    tocca nessuna riga, quella risorsa e' stata presa da qualcun altro e tutto viene annullato
    (savepoint), cosi' la proposta resta com'era e si puo' riproporre.
    """
    booking = get_booking(session, booking_id, user_id)
    if booking.status == "confirmed":
        raise BookingError("Questa prenotazione e' gia' confermata.")
    if booking.status != "proposed":
        raise BookingError("Questa prenotazione e' stata annullata e non si puo' confermare.")

    people = booking.travelers

    with session.begin_nested():
        for leg in booking.flights:
            taken = session.execute(
                update(Flight).where(Flight.id == leg.flight_id, Flight.seats_left >= people)
                .values(seats_left=Flight.seats_left - people)
            ).rowcount
            if not taken:
                label = "volo di andata" if leg.direction == "out" else "volo di ritorno"
                raise BookingError(f"Non ci sono piu' abbastanza posti sul {label}.")

        for stay in booking.rooms:
            taken = session.execute(
                update(RoomAvailability)
                .where(RoomAvailability.id == stay.room_availability_id, RoomAvailability.is_free.is_(True))
                .values(is_free=False)
            ).rowcount
            if not taken:
                night = stay.room_availability
                raise BookingError(f"La camera {night.room.name} non e' piu' libera la notte del {night.night:%d/%m}.")

        for pick in booking.activities:
            taken = session.execute(
                update(ActivityAvailability)
                .where(ActivityAvailability.id == pick.activity_availability_id, ActivityAvailability.spots_left >= people)
                .values(spots_left=ActivityAvailability.spots_left - people)
            ).rowcount
            if not taken:
                slot = pick.activity_availability
                raise BookingError(f"Non ci sono piu' posti per \"{slot.activity.name}\" il {slot.day:%d/%m}.")

        booking.status = "confirmed"
    session.flush()
    logger.info("Prenotazione %s CONFERMATA (utente %s): posti, camere e attivita' scalati", booking.id, user_id)
    return booking

def cancel_booking(session: Session, booking_id: int, user_id: int) -> Booking:
    """Annulla una prenotazione. Se era confermata rimette a disposizione posti e camere."""
    booking = get_booking(session, booking_id, user_id)
    if booking.status == "cancelled":
        raise BookingError("Questa prenotazione e' gia' annullata.")

    era_confermata = (booking.status == "confirmed")
    if era_confermata:
        people = booking.travelers
        for leg in booking.flights:
            session.execute(
                update(Flight).where(Flight.id == leg.flight_id).values(seats_left=Flight.seats_left + people)
            )
        night_ids = [stay.room_availability_id for stay in booking.rooms]
        session.execute(update(RoomAvailability).where(RoomAvailability.id.in_(night_ids)).values(is_free=True))
        for pick in booking.activities:
            session.execute(
                update(ActivityAvailability).where(ActivityAvailability.id == pick.activity_availability_id)
                .values(spots_left=ActivityAvailability.spots_left + people)
            )

    booking.status = "cancelled"
    session.flush()
    logger.info("Prenotazione %s ANNULLATA (utente %s): disponibilita' %s", booking.id, user_id, "ripristinata" if era_confermata else "non toccata")
    return booking

def user_bookings(session: Session, user_id: int) -> list[Booking]:
    """Tutte le prenotazioni e proposte dell'utente, dalla piu' recente."""
    return list(session.scalars(
        select(Booking).where(Booking.user_id == user_id).order_by(Booking.id.desc())
    ))
