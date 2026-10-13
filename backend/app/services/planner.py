"""Planner deterministico: costruisce itinerari validi, senza LLM e senza scrivere sul DB.

Dato budget, nazione, preferenze, mese, viaggiatori e durata, enumera le combinazioni
(volo di andata, volo di ritorno, hotel), assegna un'attivita' a ogni giorno, scarta cio'
che supera il budget e restituisce fino a k itinerari validi e DIVERSI tra loro.
Budget e disponibilita' sono garantiti dal codice; all'LLM resta scegliere e raccontare.
"""

import calendar
import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Activity, ActivityAvailability, Flight, Hotel, Room, RoomAvailability
from app.schemas.itinerary import (
    ActivityDay,
    ActivityPick,
    CostBreakdown,
    FlightLeg,
    HotelStay,
    Itinerary,
    PlanningFailure,
    PlanResult,
    Requirements,
    RoomNight,
    RoomStay,
)
from app.services.rag import rank_activities

logger = logging.getLogger(__name__)

# (preferenze, nazione) -> [(activity_id, punteggio)]: iniettabile per testare senza Chroma
Ranker = Callable[[list[str], str], list[tuple[int, float]]]

LABEL_MATCH = "Più adatto a te"
LABEL_CHEAPEST = "Più economico"
LABEL_ALTERNATIVE = "Alternativa"

def money(value) -> Decimal:
    return Decimal(str(value))

def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)

def departure_window(month: int, today: date) -> tuple[date, date]:
    """Primo e ultimo giorno di partenza possibili: il mese richiesto, da domani in poi,
    nell'anno piu' vicino (se il mese e' gia' passato o finito si passa all'anno dopo)."""
    for year in (today.year, today.year + 1):
        first = max(date(year, month, 1), today + timedelta(days=1))
        last = date(year, month, calendar.monthrange(year, month)[1])
        if first <= last:
            return first, last

# --- strutture interne ------------------------------------------------------

class ActivityPlan:
    """Un'attivita' (o niente) per ogni giorno del soggiorno."""

    def __init__(
        self,
        picks: dict[date, tuple[Activity, ActivityAvailability] | None],  # None = giorno libero
        cost: Decimal,
        affinity: float,
    ):
        self.picks = picks
        self.cost = cost
        self.affinity = affinity

# Una camera scelta con le sue righe di disponibilita' (una per notte, in ordine)
RoomPick = tuple[Room, list[RoomAvailability]]

class Candidate:
    """Una combinazione completa (voli + hotel + attivita') con i suoi costi."""

    def __init__(
        self,
        city: str,
        flight_out: Flight,
        flight_return: Flight,
        hotel: Hotel,
        rooms: list["RoomPick"],
        plan: ActivityPlan,
        flights_cost: Decimal,
        hotel_cost: Decimal,
    ):
        self.city = city
        self.flight_out = flight_out
        self.flight_return = flight_return
        self.hotel = hotel
        self.rooms = rooms
        self.plan = plan
        self.flights_cost = flights_cost
        self.hotel_cost = hotel_cost

    @property
    def total(self) -> Decimal:
        return self.flights_cost + self.hotel_cost + self.plan.cost

class CityData:
    """Tutto cio' che serve per pianificare in una citta', caricato in blocco."""

    def __init__(
        self,
        outbound: list[Flight],
        returns_by_day: dict[date, list[Flight]],
        hotels: list[Hotel],
        rooms_by_hotel: dict[int, list[Room]],
        free_rows: dict[tuple[int, date], RoomAvailability],  # (room_id, notte) -> riga, solo se la camera e' libera
        activity_options: dict[date, list[tuple[Activity, ActivityAvailability]]],
    ):
        self.outbound = outbound
        self.returns_by_day = returns_by_day
        self.hotels = hotels
        self.rooms_by_hotel = rooms_by_hotel
        self.free_rows = free_rows
        self.activity_options = activity_options

# --- attivita' --------------------------------------------------------------

ActivityOptions = dict[date, list[tuple[Activity, ActivityAvailability]]]

def assign_activities(
    dates: list[date],
    options: ActivityOptions,
    travelers: int,
    affinity: dict[int, float],
    score: Callable[[Activity], tuple],
) -> ActivityPlan:
    """Una attivita' per ogni giorno, senza ripetizioni quando possibile.

    Prima si cerca di dare a ogni giorno un'attivita' diversa (abbinamento giorni-attivita': se un giorno
    resterebbe senza, si prova a spostare un'attivita' gia' assegnata a un altro giorno, cosi' si riempiono
    piu' giorni possibile; a parita' si preferisce il punteggio migliore). Se le attivita' diverse finiscono
    (viaggi lunghi) si ripete la migliore disponibile in quel giorno. Un giorno resta libero (None) solo se
    in quella data non c'e' nessuna attivita' disponibile.
    """
    # per ogni giorno le attivita' disponibili, dalla migliore alla peggiore (a parita': id piu' basso)
    def per_punteggio(pair):
        return (score(pair[0]), -pair[0].id)

    ordered = {}
    for day in dates:
        ordered[day] = sorted(options.get(day, []), key=per_punteggio, reverse=True)
    owner: dict[int, date] = {}  # id attivita' -> giorno in cui e' stata messa
    picks: dict[date, tuple[Activity, ActivityAvailability] | None] = {day: None for day in dates}

    def place(day: date, seen: set[int]) -> bool:
        for pair in ordered[day]:
            activity_id = pair[0].id
            if activity_id in seen:
                continue
            seen.add(activity_id)
            if activity_id not in owner or place(owner[activity_id], seen):  # libera, oppure l'altro giorno ne trova un'altra
                owner[activity_id] = day
                picks[day] = pair
                return True
        return False

    def per_scelta(d):
        return (len(ordered[d]), d)

    for day in sorted(dates, key=per_scelta):  # prima i giorni con meno scelta
        place(day, set())

    # le attivita' diverse sono finite: si ripete la migliore disponibile del giorno
    for day in dates:
        if picks[day] is None and ordered[day]:
            picks[day] = ordered[day][0]

    chosen = [pair for pair in picks.values() if pair is not None]
    return ActivityPlan(
        picks={day: picks[day] for day in sorted(picks)},
        cost=sum((money(activity.price) * travelers for activity, _ in chosen), Decimal(0)),
        affinity=sum(affinity.get(activity.id, 0.0) for activity, _ in chosen),
    )

def plans_for(dates: list[date], options: ActivityOptions, travelers: int, affinity: dict[int, float]) -> list[ActivityPlan]:
    """I due piani di attivita' per le stesse date, dal piu' adatto al piu' economico:
    "match" (solo affinita') ed "economico" (l'attivita' piu' a buon mercato di ogni giorno)."""
    def per_affinita(a):
        return (affinity.get(a.id, 0.0),)

    def per_prezzo(a):
        return (-float(a.price), affinity.get(a.id, 0.0))

    return [
        assign_activities(dates, options, travelers, affinity, per_affinita),
        assign_activities(dates, options, travelers, affinity, per_prezzo),
    ]

# --- caricamento dati -------------------------------------------------------

def load_city(session: Session, req: Requirements, home: str, city: str, first: date, last: date) -> CityData:
    """Carica in blocco tutto cio' che serve per una citta' (poche query, poi si lavora in memoria)."""
    stay_end = last + timedelta(days=req.nights + 2)  # primo giorno che non serve piu'

    outbound = session.scalars(
        select(Flight)
        .where(
            Flight.origin_airport == home, Flight.city == city, Flight.seats_left >= req.travelers,
            Flight.departure >= day_start(first), Flight.departure < day_start(last + timedelta(days=1)),
        )
        .order_by(Flight.departure, Flight.id)
    ).all()

    returns = session.scalars(
        select(Flight)
        .where(
            Flight.destination_airport == home, Flight.city == city, Flight.seats_left >= req.travelers,
            Flight.departure >= day_start(first + timedelta(days=req.nights)), Flight.departure < day_start(stay_end),
        )
        .order_by(Flight.departure, Flight.id)
    ).all()
    returns_by_day: dict[date, list[Flight]] = {}
    for flight in returns:
        returns_by_day.setdefault(flight.departure.date(), []).append(flight)

    hotels = session.scalars(select(Hotel).where(Hotel.city == city).order_by(Hotel.id)).all()
    rooms_by_hotel: dict[int, list[Room]] = {hotel.id: [] for hotel in hotels}
    rooms = session.scalars(select(Room).where(Room.hotel_id.in_([hotel.id for hotel in hotels])).order_by(Room.id)).all()
    for room in rooms:
        rooms_by_hotel[room.hotel_id].append(room)
    free_rows = {
        (row.room_id, row.night): row
        for row in session.scalars(
            select(RoomAvailability).where(
                RoomAvailability.room_id.in_([room.id for room in rooms]),
                RoomAvailability.night >= first, RoomAvailability.night < stay_end,
                RoomAvailability.is_free,
            )
        )
    }

    activity_options: ActivityOptions = {}
    for activity, slot in session.execute(
        select(Activity, ActivityAvailability)
        .join(ActivityAvailability, ActivityAvailability.activity_id == Activity.id)
        .where(
            Activity.city == city, ActivityAvailability.spots_left >= req.travelers,
            ActivityAvailability.day >= first, ActivityAvailability.day < stay_end,
        )
        .order_by(Activity.id)
    ):
        activity_options.setdefault(slot.day, []).append((activity, slot))

    return CityData(list(outbound), returns_by_day, list(hotels), rooms_by_hotel, free_rows, activity_options)

# --- camere -----------------------------------------------------------------

def pick_rooms(
    rooms: list[Room], free_rows: dict[tuple[int, date], RoomAvailability], nights: list[date], travelers: int
) -> tuple[list[RoomPick], Decimal] | None:
    """Le camere piu' economiche dello stesso hotel che ospitano tutti i viaggiatori.

    Una camera e' utilizzabile solo se e' libera in TUTTE le notti. Un hotel ha poche camere,
    quindi si provano tutti i sottoinsiemi: il risultato e' il costo minimo esatto (a parita'
    meno camere, poi gli id). Restituisce None se l'hotel non puo' ospitare il gruppo.
    """
    usable = []
    for room in rooms:
        stay = [free_rows.get((room.id, night)) for night in nights]
        if all(stay):
            usable.append((room, stay, sum((money(row.price_per_night) for row in stay), Decimal(0))))

    best = None
    for size in range(1, len(usable) + 1):
        for group in combinations(usable, size):
            if sum(room.capacity for room, _, _ in group) < travelers:
                continue
            key = (sum((cost for _, _, cost in group), Decimal(0)), size, [room.id for room, _, _ in group])
            if best is None or key < best[0]:
                best = (key, [(room, stay) for room, stay, _ in group])
    return None if best is None else (best[1], best[0][0])

# --- selezione --------------------------------------------------------------

def tie_break(c: Candidate) -> tuple:
    """In coda a ogni chiave di ordinamento: a parita' il risultato e' sempre lo stesso."""
    return (c.flight_out.departure, c.flight_out.id, c.flight_return.id, c.hotel.id)

def match_key(c: Candidate) -> tuple:
    """Per "Più adatto a te": prima l'affinita', poi le stelle, poi il prezzo."""
    return (-round(c.plan.affinity, 6), -c.hotel.stars, c.total, *tie_break(c))

def cheapest_key(c: Candidate) -> tuple:
    """Per "Più economico": prima il prezzo, poi l'affinita', poi le stelle."""
    return (c.total, -round(c.plan.affinity, 6), -c.hotel.stars, *tie_break(c))

def select_itineraries(valid: list[Candidate], k: int) -> list[tuple[str, Candidate]]:
    """Il migliore per affinita' e il piu' economico, poi le k alternative piu' adatte.
    Se i primi due coincidono resta uno solo con l'etichetta unita: ogni etichetta e' sempre vera."""
    best_match = min(valid, key=match_key)
    best_cheapest = min(valid, key=cheapest_key)

    if best_match is best_cheapest:
        chosen = [(LABEL_MATCH + " e " + LABEL_CHEAPEST.lower(), best_match)]
    else:
        chosen = [(LABEL_MATCH, best_match), (LABEL_CHEAPEST, best_cheapest)]

    others = [c for c in sorted(valid, key=match_key) if c is not best_match and c is not best_cheapest]
    return chosen + [(LABEL_ALTERNATIVE, c) for c in others[:k]]

# --- conversione in schema --------------------------------------------------

def to_leg(flight: Flight) -> FlightLeg:
    return FlightLeg(
        flight_id=flight.id, origin=flight.origin_airport, destination=flight.destination_airport,
        departure=flight.departure, arrival=flight.arrival, price_per_person=float(flight.price),
    )

def to_itinerary(label: str, c: Candidate, req: Requirements, affinity: dict[int, float]) -> Itinerary:
    days = []
    for day, pair in c.plan.picks.items():
        pick = None
        if pair is not None:
            activity, slot = pair
            pick = ActivityPick(
                availability_id=slot.id, activity_id=activity.id, name=activity.name,
                category=activity.category, price_per_person=float(activity.price),
                affinity=round(affinity.get(activity.id, 0.0), 4),
            )
        days.append(ActivityDay(day=day, activity=pick))

    return Itinerary(
        label=label, country=req.country, city=c.city, travelers=req.travelers, nights=req.nights,
        departure_date=c.flight_out.departure.date(), return_date=c.flight_return.departure.date(),
        flight_out=to_leg(c.flight_out), flight_return=to_leg(c.flight_return),
        hotel=HotelStay(
            hotel_id=c.hotel.id, name=c.hotel.name, stars=c.hotel.stars,
            image_url=c.hotel.image_url, image_credit=c.hotel.image_credit,
            rooms=[
                RoomStay(
                    room_id=room.id, name=room.name, capacity=room.capacity,
                    nights=[RoomNight(availability_id=r.id, night=r.night, price=float(r.price_per_night)) for r in stay],
                )
                for room, stay in c.rooms
            ],
        ),
        days=days,
        costs=CostBreakdown(
            flights=float(c.flights_cost), hotel=float(c.hotel_cost),
            activities=float(c.plan.cost), total=float(c.total),
        ),
        affinity=round(c.plan.affinity, 4),
        free_days=sum(1 for day in days if day.activity is None),
    )

def failure(
    pairs_found: bool, hotel_found: bool, activities_found: bool, min_cost: Decimal | None, req: Requirements,
) -> PlanningFailure:
    """Perche' non c'e' nessun itinerario: la causa piu' a monte tra voli, attivita', hotel e budget."""
    if not pairs_found:
        return PlanningFailure(
            code="no_flights",
            message=f"Non trovo voli di andata e ritorno per {req.nights} notti nel mese richiesto.",
        )
    if not activities_found:
        return PlanningFailure(
            code="no_activities",
            message=f"Non trovo attivita' disponibili per ogni giorno di {req.nights} notti in {req.country} nel mese richiesto.",
        )
    if not hotel_found:
        return PlanningFailure(
            code="no_hotel",
            message=f"Non trovo un hotel con camere libere per tutte le {req.nights} notti e per {req.travelers} persone.",
        )
    return PlanningFailure(
        code="over_budget", min_cost=float(min_cost),
        message=f"Con questo budget non riesco a costruire il viaggio: servono almeno {min_cost:.2f} euro.",
    )

# --- punto di ingresso ------------------------------------------------------

def city_candidates(
    session: Session, req: Requirements, home: str, city: str, first: date, last: date, affinity: dict[int, float]
) -> tuple[list[Candidate], bool, bool]:
    """Tutte le combinazioni volo andata + volo ritorno + hotel + piano attivita' di una citta', budget a parte.
    Per ogni combinazione di voli e hotel il piano piu' adatto viene prima di quello piu' economico.
    Un piano con un giorno senza attivita' non vale: ogni giorno deve avere la sua.
    Restituisce anche se esiste una coppia di voli andata/ritorno e se per essa ci sono attivita' ogni giorno."""
    data = load_city(session, req, home, city, first, last)
    candidates: list[Candidate] = []
    pairs_found = activities_found = False
    plans_by_arrival: dict[date, list[ActivityPlan]] = {}
    stays: dict[tuple[int, date], tuple[list[RoomPick], Decimal] | None] = {}  # (hotel, arrivo) -> camere

    for out in data.outbound:
        arrival = out.arrival.date()
        nights = [arrival + timedelta(days=i) for i in range(req.nights)]
        if arrival not in plans_by_arrival:  # le attivita' dipendono solo dalle date
            plans = plans_for(nights, data.activity_options, req.travelers, affinity)
            plans_by_arrival[arrival] = [p for p in plans if all(pick is not None for pick in p.picks.values())]

        for back in data.returns_by_day.get(arrival + timedelta(days=req.nights), []):
            pairs_found = True
            activities_found = activities_found or bool(plans_by_arrival[arrival])
            flights_cost = (money(out.price) + money(back.price)) * req.travelers

            for hotel in data.hotels:
                if (hotel.id, arrival) not in stays:  # le camere dipendono solo dall'hotel e dalle date
                    stays[hotel.id, arrival] = pick_rooms(
                        data.rooms_by_hotel[hotel.id], data.free_rows, nights, req.travelers
                    )
                stay = stays[hotel.id, arrival]
                if stay is None:
                    continue  # nessun gruppo di camere libere per tutte le notti ospita i viaggiatori
                rooms, hotel_cost = stay

                for plan in plans_by_arrival[arrival]:
                    candidates.append(Candidate(city, out, back, hotel, rooms, plan, flights_cost, hotel_cost))

    return candidates, pairs_found, activities_found

def plan_trips(
    session: Session,
    req: Requirements,
    home_airport: str,
    today: date | None = None,
    k: int = settings.planner_alternatives,
    ranker: Ranker = rank_activities,
) -> PlanResult:
    """I due itinerari in evidenza piu' fino a k alternative (le piu' rilevanti), oppure un fallimento motivato. Sola lettura."""
    today = today or date.today()
    cities = sorted(set(session.scalars(select(Hotel.city).where(Hotel.country == req.country))))
    if not cities:
        logger.warning("Planner: nazione sconosciuta %r", req.country)
        return PlanResult(failure=PlanningFailure(
            code="unknown_country", message=f"Non ho viaggi disponibili per '{req.country}'.",
        ))

    first, last = departure_window(req.month, today)
    if req.departure_date:  # data esatta richiesta: si parte solo quel giorno (se e' nel mese e da domani in poi)
        if not first <= req.departure_date <= last:
            return PlanResult(failure=PlanningFailure(
                code="no_flights", message=f"La data di partenza {req.departure_date} non e' valida: deve essere futura e nel mese richiesto.",
            ))
        first = last = req.departure_date
    affinity =dict(ranker(req.activities, req.country))

    candidates: list[Candidate] = []
    pairs_found = activities_found = False
    for city in cities:
        found, city_pairs, city_activities = city_candidates(session, req, home_airport, city, first, last, affinity)
        candidates += found
        pairs_found = pairs_found or city_pairs
        activities_found = activities_found or city_activities

    # Per ogni combinazione di voli e hotel si tiene il primo piano (il piu' adatto) che sta nel budget
    budget = money(req.budget)
    valid: list[Candidate] = []
    already_taken = set()
    for c in candidates:
        key = (c.flight_out.id, c.flight_return.id, c.hotel.id)
        if c.total <= budget and key not in already_taken:
            already_taken.add(key)
            valid.append(c)

    if not valid:
        min_cost = min((c.total for c in candidates), default=None)  # il costo minimo che il planner sa costruire
        result = failure(pairs_found, bool(candidates), activities_found, min_cost, req)
        logger.info("Planner: nessun itinerario per %s (%s, budget %s)", req.country, result.code, req.budget)
        return PlanResult(failure=result)

    chosen = select_itineraries(valid, k)
    logger.info(
        "Planner: %s, %d notti, %d viaggiatori, budget %s: %d candidati validi, %d itinerari proposti",
        req.country, req.nights, req.travelers, req.budget, len(valid), len(chosen),
    )
    return PlanResult(itineraries=[to_itinerary(label, c, req, affinity) for label, c in chosen])
