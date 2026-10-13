"""Test delle prenotazioni: conferma e annullamento scalano/ripristinano le disponibilita' in modo atomico."""

import json
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.models.models import Activity, ActivityAvailability, Flight, RoomAvailability, User
from app.schemas.itinerary import (
    ActivityDay,
    ActivityPick,
    CostBreakdown,
    FlightLeg,
    HotelStay,
    Itinerary,
    Requirements,
    RoomNight,
    RoomStay,
)
from app.services import booking
from app.services.agent_tools import AgentContext, build_tools
from app.services.booking import BookingError
from app.services.planner import plan_trips
from db_scripts.seed import seed

TODAY = date(2026, 10, 12)
TRAVELERS = 2

@pytest.fixture
def world():
    """Database seminato da zero per ogni test: la conferma modifica le disponibilita'."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    seed(session, start=TODAY)
    session.add(User(email="altro@example.com", password_hash="x", name="Altro"))
    session.flush()
    yield session
    session.close()

@pytest.fixture
def proposal(world):
    """Una proposta salvata dall'utente demo (id 1)."""
    def ranker(preferences, country):  # senza RAG: tutte le attivita' della nazione con lo stesso punteggio
        return [(a.id, 0.5) for a in world.scalars(select(Activity).where(Activity.country == country))]

    req = Requirements(budget=4000, country="Spagna", activities=["cultura"], month=11, travelers=TRAVELERS, nights=5)
    itinerary = plan_trips(world, req, "MXP", today=TODAY, ranker=ranker).itineraries[0]
    saved = booking.create_proposal(world, 1, None, itinerary)
    return saved

def trip_of(saved) -> Itinerary:
    """Un itinerario equivalente alla proposta salvata (solo i campi che create_proposal legge)."""
    legs = {f.direction: FlightLeg(flight_id=f.flight_id, origin="", destination="", departure=datetime(2026, 1, 1),
                                   arrival=datetime(2026, 1, 1), price_per_person=float(f.price_per_person)) for f in saved.flights}
    nights = [RoomNight(availability_id=r.room_availability_id, night=date(2026, 1, 1), price=float(r.price)) for r in saved.rooms]
    days = [ActivityDay(day=date(2026, 1, 1), activity=ActivityPick(
        availability_id=a.activity_availability_id, activity_id=0, name="", category="",
        price_per_person=float(a.price_per_person), affinity=a.affinity)) for a in saved.activities]
    return Itinerary(
        label=saved.label, country=saved.country, city=saved.city, travelers=saved.travelers, nights=saved.nights,
        departure_date=saved.departure_date, return_date=saved.return_date,
        flight_out=legs["out"], flight_return=legs["return"],
        hotel=HotelStay(hotel_id=saved.hotel_id, name="", stars=1,
                        rooms=[RoomStay(room_id=0, name="", capacity=1, nights=nights)]),
        days=days, costs=CostBreakdown(flights=0, hotel=0, activities=0, total=float(saved.total_cost)),
        affinity=0, free_days=0,
    )

def snapshot(session, saved) -> dict:
    """Le disponibilita' toccate da una prenotazione, per confrontarle prima/dopo."""
    seats = {f.flight_id: session.get(Flight, f.flight_id).seats_left for f in saved.flights}
    rooms = [session.get(RoomAvailability, r.room_availability_id).is_free for r in saved.rooms]
    spots = [session.get(ActivityAvailability, a.activity_availability_id).spots_left for a in saved.activities]
    return {"seats": seats, "rooms": rooms, "spots": spots}

def test_confirm_takes_flights_rooms_and_activities(world, proposal):
    before = snapshot(world, proposal)
    confirmed = booking.confirm_booking(world, proposal.id, 1)
    after = snapshot(world, proposal)

    assert confirmed.status == "confirmed"
    assert all(after["seats"][i] == before["seats"][i] - TRAVELERS for i in before["seats"])
    assert before["rooms"] == [True] * len(before["rooms"]) and after["rooms"] == [False] * len(after["rooms"])
    assert after["spots"] == [s - TRAVELERS for s in before["spots"]]

def test_cancel_restores_everything(world, proposal):
    before = snapshot(world, proposal)
    booking.confirm_booking(world, proposal.id, 1)
    cancelled = booking.cancel_booking(world, proposal.id, 1)

    assert cancelled.status == "cancelled"
    assert snapshot(world, proposal) == before

def test_cancelling_a_proposal_does_not_touch_availability(world, proposal):
    before = snapshot(world, proposal)
    assert booking.cancel_booking(world, proposal.id, 1).status == "cancelled"
    assert snapshot(world, proposal) == before

def test_confirm_twice_is_refused(world, proposal):
    booking.confirm_booking(world, proposal.id, 1)
    with pytest.raises(BookingError, match="gia' confermata"):
        booking.confirm_booking(world, proposal.id, 1)

def test_a_taken_resource_cancels_the_whole_confirmation(world, proposal):
    before = snapshot(world, proposal)
    last_night = proposal.rooms[-1].room_availability_id
    world.get(RoomAvailability, last_night).is_free = False  # un altro cliente prende la camera
    world.flush()

    with pytest.raises(BookingError, match="non e' piu' libera"):
        booking.confirm_booking(world, proposal.id, 1)

    after = snapshot(world, proposal)
    assert after["seats"] == before["seats"] and after["spots"] == before["spots"]  # il volo non e' stato scalato
    assert after["rooms"][:-1] == before["rooms"][:-1]  # le altre notti sono ancora libere
    assert proposal.status == "proposed"

def test_not_enough_seats_is_refused(world, proposal):
    world.get(Flight, proposal.flights[0].flight_id).seats_left = TRAVELERS - 1
    world.flush()
    with pytest.raises(BookingError, match="volo di andata"):
        booking.confirm_booking(world, proposal.id, 1)

def test_other_users_cannot_touch_my_booking(world, proposal):
    other = world.scalar(select(User.id).where(User.email == "altro@example.com"))
    with pytest.raises(BookingError, match="Non trovo"):
        booking.confirm_booking(world, proposal.id, other)
    with pytest.raises(BookingError, match="Non trovo"):
        booking.cancel_booking(world, proposal.id, other)

def test_list_shows_every_status(world, proposal):
    assert [b.id for b in booking.user_bookings(world, 1)] == [proposal.id]
    booking.cancel_booking(world, proposal.id, 1)
    assert [b.status for b in booking.user_bookings(world, 1)] == ["cancelled"]

# --- tool dell'agente -------------------------------------------------------

@pytest.fixture
def tools(world, proposal):
    ctx = AgentContext(world, user_id=1, today=TODAY)
    ctx.last_proposal_id = proposal.id
    return {t.name: t for t in build_tools(ctx)}

def test_confirm_tool_uses_the_last_proposal(tools, world, proposal):
    data = json.loads(tools["confirm_booking"].invoke({}))
    assert data["prenotazione_confermata"]["stato"] == "confirmed"
    assert data["prenotazione_confermata"]["id"] == proposal.id

def test_confirm_tool_explains_a_failure(tools, world, proposal):
    tools["confirm_booking"].invoke({})
    assert "gia' confermata" in tools["confirm_booking"].invoke({})

def test_confirm_tool_without_a_proposal(world):
    ctx = AgentContext(world, user_id=1, today=TODAY)
    answer = {t.name: t for t in build_tools(ctx)}["confirm_booking"].invoke({})
    assert "nessuna proposta" in answer

def test_cancel_and_list_tools(tools, proposal):
    tools["confirm_booking"].invoke({})
    listed = json.loads(tools["list_my_bookings"].invoke({}))
    assert [b["stato"] for b in listed] == ["confirmed"]
    data = json.loads(tools["cancel_booking"].invoke({"booking_id": proposal.id}))
    assert data["prenotazione_annullata"]["stato"] == "cancelled"

def test_anonymous_user_cannot_book(world):
    ctx = AgentContext(world, user_id=None, today=TODAY)
    t = {x.name: x for x in build_tools(ctx)}
    assert "autenticato" in t["confirm_booking"].invoke({})
    assert "autenticato" in t["cancel_booking"].invoke({"booking_id": 1})
