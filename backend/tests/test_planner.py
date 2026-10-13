"""Test del planner: itinerari validi, budget, durata, fallimenti e salvataggio della proposta.

Si usa il seed completo con "oggi" fissato al 12/10/2026 e un ranker finto (per categoria):
cosi' il planner si testa senza Chroma e senza LLM. Un solo test usa il RAG vero.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.db.session import Base, SessionLocal, engine
from app.models.models import (
    Activity,
    ActivityAvailability,
    Booking,
    Conversation,
    Flight,
    Hotel,
    Room,
    RoomAvailability,
)
from app.schemas.itinerary import Itinerary, Requirements
from app.services.booking import create_proposal
from app.services.planner import assign_activities, departure_window, plan_trips
from app.services.rag import index_activities, reset_collection
from db_scripts.seed import seed

TODAY = date(2026, 10, 12)
HOME = "MXP"
DEMO_USER_ID = 1  # creato dal seed

BASE = dict(budget=2500, country="Spagna", activities=["cultura", "relax"], month=11)
SCENARIOS = [
    pytest.param({}, id="base"),
    pytest.param(dict(travelers=3, budget=4000), id="3-viaggiatori"),
    pytest.param(
        dict(travelers=4, country="Grecia", month=12, nights=5, budget=8000, activities=["relax", "gastronomia"]),
        id="4-viaggiatori-grecia-5-notti",
    ),
    pytest.param(
        dict(travelers=2, country="Norvegia", month=8, budget=6000, activities=["sport", "natura"]),
        id="norvegia-agosto-2027",
    ),
]

@pytest.fixture(scope="module")
def world():
    """Database seminato una sola volta per tutto il modulo."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    seed(session, start=TODAY)
    activities = [(a.id, a.country, a.category) for a in session.scalars(select(Activity))]
    yield SimpleNamespace(session=session, activities=activities)
    session.close()

@pytest.fixture
def session(world):
    """La sessione del modulo; a fine test si annulla tutto cio' che non e' stato confermato."""
    yield world.session
    world.session.rollback()

def category_ranker(world):
    """Ranker finto: 0,8 se la categoria coincide con una preferenza, 0,2 altrimenti."""

    def rank(preferences, country):
        scores = {
            activity_id: max(0.8 if category == p else 0.2 for p in preferences)
            for activity_id, activity_country, category in world.activities
            if activity_country == country
        }
        def per_punteggio(pair):
            return -pair[1]

        return sorted(scores.items(), key=per_punteggio)

    return rank

def run(world, session, today=TODAY, **overrides):
    req = Requirements(**{**BASE, **overrides})
    return req, plan_trips(session, req, HOME, today=today, ranker=category_ranker(world))

def check_itinerary(session, it, req):
    """Verifica contro il database che l'itinerario rispetti tutti i vincoli."""
    assert it.nights == req.nights == len(it.days)
    assert it.costs.total <= req.budget

    # voli
    out = session.get(Flight, it.flight_out.flight_id)
    back = session.get(Flight, it.flight_return.flight_id)
    assert (out.origin_airport, out.city) == (HOME, it.city)
    assert (back.destination_airport, back.city) == (HOME, it.city)
    assert out.seats_left >= req.travelers and back.seats_left >= req.travelers
    assert out.departure.month == req.month

    # notti consecutive dall'arrivo; il ritorno parte il giorno dopo l'ultima notte
    arrival = out.arrival.date()
    expected_nights = [arrival + timedelta(days=i) for i in range(req.nights)]
    assert [d.day for d in it.days] == expected_nights
    assert back.departure.date() == expected_nights[-1] + timedelta(days=1) == it.return_date

    # hotel
    hotel = session.get(Hotel, it.hotel.hotel_id)
    assert hotel.city == it.city
    capacity = sum(stay.capacity for stay in it.hotel.rooms)
    assert capacity >= req.travelers
    assert len({stay.room_id for stay in it.hotel.rooms}) == len(it.hotel.rooms)
    for stay in it.hotel.rooms:
        assert capacity - stay.capacity < req.travelers  # nessuna camera in piu' del necessario
        room = session.get(Room, stay.room_id)
        assert (room.hotel_id, room.capacity) == (hotel.id, stay.capacity)
        assert [n.night for n in stay.nights] == expected_nights
        for night in stay.nights:
            row = session.get(RoomAvailability, night.availability_id)
            assert (row.room_id, row.night) == (room.id, night.night)
            assert row.is_free

    # attivita': disponibili quel giorno, nella citta'; mai ripetute (14 per citta', al massimo 14 notti)
    seen = set()
    for day in it.days:
        if day.activity is None:
            continue
        slot = session.get(ActivityAvailability, day.activity.availability_id)
        activity = session.get(Activity, day.activity.activity_id)
        assert slot.day == day.day and slot.spots_left >= req.travelers
        assert activity.city == it.city
        assert activity.id not in seen
        seen.add(activity.id)

    # costi
    flights = (it.flight_out.price_per_person + it.flight_return.price_per_person) * req.travelers
    hotel_cost = sum(n.price for stay in it.hotel.rooms for n in stay.nights)
    activities = sum(d.activity.price_per_person for d in it.days if d.activity) * req.travelers
    assert it.costs.flights == pytest.approx(flights, abs=0.01)
    assert it.costs.hotel == pytest.approx(hotel_cost, abs=0.01)
    assert it.costs.activities == pytest.approx(activities, abs=0.01)
    assert it.costs.total == pytest.approx(flights + hotel_cost + activities, abs=0.01)

# --- itinerari validi -------------------------------------------------------

@pytest.mark.parametrize("overrides", SCENARIOS)
def test_every_itinerary_respects_all_constraints(world, session, overrides):
    req, result = run(world, session, **overrides)

    assert result.ok, result.failure
    assert 1 <= len(result.itineraries) <= 2 + 3
    for itinerary in result.itineraries:
        check_itinerary(session, itinerary, req)

def test_itineraries_are_different_from_each_other(world, session):
    _, result = run(world, session)
    places = [(it.city, it.hotel.hotel_id, it.flight_out.flight_id, it.flight_return.flight_id) for it in result.itineraries]
    assert len(set(places)) == len(places)

def test_labels_are_always_true(world, session):
    for overrides in ({}, dict(budget=900), dict(budget=1500)):
        _, result = run(world, session, **overrides)
        its = result.itineraries
        for it in its:
            label = it.label.lower()
            if "economico" in label:
                assert it.costs.total <= min(o.costs.total for o in its)
            if "adatto" in label:
                assert it.affinity >= max(o.affinity for o in its)

# --- durata, viaggiatori, preferenze ----------------------------------------

def test_standard_plan_is_seven_nights(world, session):
    _, result = run(world, session)
    assert settings.default_nights == 7
    assert {it.nights for it in result.itineraries} == {7}

@pytest.mark.parametrize("nights", [3, 5, 10])
def test_requested_duration_is_respected(world, session, nights):
    req, result = run(world, session, nights=nights, budget=4000)

    assert result.ok, result.failure
    assert {it.nights for it in result.itineraries} == {nights}
    check_itinerary(session, result.itineraries[0], req)

def test_exact_departure_date_is_respected(world, session):
    _, first_try = run(world, session, nights=5, budget=4000)
    wanted = max(it.departure_date for it in first_try.itineraries)  # una data diversa dalla prima possibile

    req, result = run(world, session, nights=5, budget=4000, departure_date=wanted)

    assert result.ok, result.failure
    assert {it.departure_date for it in result.itineraries} == {wanted}
    check_itinerary(session, result.itineraries[0], req)

def test_departure_date_outside_the_month_is_refused(world, session):
    _, result = run(world, session, departure_date=date(2026, 12, 5))  # BASE e' novembre

    assert not result.ok
    assert result.failure.code == "no_flights"

def test_every_day_has_an_activity(world, session):
    """Mai giorni liberi: neanche nei viaggi lunghi (fino a 14 notti)."""
    for nights in (5, 7, 10, 14):
        _, result = run(world, session, nights=nights, budget=6000)
        assert result.ok, (nights, result.failure)
        for itinerary in result.itineraries:
            assert itinerary.free_days == 0
            assert all(day.activity is not None for day in itinerary.days)

def test_activities_are_not_repeated_while_there_are_different_ones(world, session):
    _, result = run(world, session, nights=7)
    for itinerary in result.itineraries:
        assert len({day.activity.activity_id for day in itinerary.days}) == 7

def test_even_the_longest_trip_has_only_different_activities(world, session):
    _, result = run(world, session, nights=14, budget=8000)  # 14 attivita' per citta', 14 giorni
    assert result.ok, result.failure
    for itinerary in result.itineraries:
        assert len({day.activity.activity_id for day in itinerary.days}) == 14

def test_assign_activities_repeats_only_when_the_different_ones_run_out():
    giorni = [date(2026, 11, 1) + timedelta(days=i) for i in range(3)]
    a, b = SimpleNamespace(id=1, price=10), SimpleNamespace(id=2, price=10)
    options = {day: [(a, "a" + str(i)), (b, "b" + str(i))] for i, day in enumerate(giorni)}  # 2 attivita', 3 giorni
    def punteggio(act):
        return (0.9 if act.id == 1 else 0.5,)

    plan = assign_activities(giorni, options, 1, {1: 0.9, 2: 0.5}, punteggio)
    assert all(pick is not None for pick in plan.picks.values())  # nessun giorno libero
    assert {pick[0].id for pick in plan.picks.values()} == {1, 2}  # prima usa entrambe, poi ripete

def test_no_itinerary_when_a_day_has_no_activity_at_all(world, session):
    session.execute(delete(ActivityAvailability))  # nessuna attivita' disponibile in nessun giorno
    try:
        _, result = run(world, session)
        assert not result.ok and result.failure.code == "no_activities"
    finally:
        session.rollback()

def test_assign_activities_moves_an_activity_to_fill_every_day():
    """Il caso in cui l'assegnazione "golosa" lasciava un giorno libero: A va bene per entrambi i giorni, B solo per il primo."""
    day1, day2 = date(2026, 11, 1), date(2026, 11, 2)
    a, b = SimpleNamespace(id=1, price=10), SimpleNamespace(id=2, price=10)
    options = {day1: [(a, "a1"), (b, "b1")], day2: [(a, "a2")]}
    def punteggio(act):
        return (0.9 if act.id == 1 else 0.1,)

    plan = assign_activities([day1, day2], options, 1, {1: 0.9, 2: 0.1}, punteggio)
    assert plan.picks[day1][0].id == 2 and plan.picks[day2][0].id == 1  # B il primo giorno, A il secondo

def test_preferences_change_the_activities(world, session):
    def count(result, category):
        return sum(1 for d in result.itineraries[0].days if d.activity and d.activity.category == category)

    _, sporty = run(world, session, activities=["sport"])
    _, relaxed = run(world, session, activities=["relax"])

    assert count(sporty, "sport") >= count(relaxed, "sport")
    assert count(relaxed, "relax") >= count(sporty, "relax")
    assert count(sporty, "sport") >= 1 and count(relaxed, "relax") >= 1

def test_a_bigger_budget_buys_a_better_hotel(world, session):
    _, tight = run(world, session, budget=800)
    _, generous = run(world, session, budget=3000)
    assert generous.itineraries[0].hotel.stars >= tight.itineraries[0].hotel.stars
    assert generous.itineraries[0].hotel.stars > tight.itineraries[0].hotel.stars

# --- fallimenti -------------------------------------------------------------

def test_budget_too_low_reports_the_minimum_cost(world, session):
    _, result = run(world, session, budget=100)

    assert not result.ok
    assert result.failure.code == "over_budget"
    assert result.failure.min_cost > 100
    assert f"{result.failure.min_cost:.2f}" in result.failure.message

def test_minimum_cost_is_exact(world, session):
    """Con budget = costo minimo dichiarato un itinerario esiste; un centesimo in meno no."""
    _, low = run(world, session, budget=100)
    minimum = low.failure.min_cost

    _, enough = run(world, session, budget=minimum)
    assert enough.ok
    assert min(it.costs.total for it in enough.itineraries) == pytest.approx(minimum, abs=0.01)

    _, short = run(world, session, budget=round(minimum - 0.01, 2))
    assert short.failure.code == "over_budget"

def test_more_travelers_need_more_budget(world, session):
    _, one = run(world, session, budget=100)
    _, three = run(world, session, budget=100, travelers=3)
    assert three.failure.min_cost > one.failure.min_cost * 2

def test_no_flights_outside_the_data_window(world, session):
    _, result = run(world, session, today=date(2027, 10, 10))  # novembre 2027: i voli finiscono a ottobre 2027
    assert result.failure.code == "no_flights"

def test_unknown_country(world, session):
    _, result = run(world, session, country="Atlantide")
    assert result.failure.code == "unknown_country"

def test_no_hotel_when_every_room_is_taken(world, session):
    spanish_rooms = select(Room.id).join(Hotel).where(Hotel.country == "Spagna")
    session.execute(update(RoomAvailability).where(RoomAvailability.room_id.in_(spanish_rooms)).values(is_free=False))  # non si fa commit: la fixture annulla a fine test

    _, result = run(world, session)
    assert result.failure.code == "no_hotel"

# --- proprieta' generali ----------------------------------------------------

def test_departure_window():
    assert departure_window(11, date(2026, 10, 12)) == (date(2026, 11, 1), date(2026, 11, 30))
    assert departure_window(10, date(2026, 10, 12)) == (date(2026, 10, 13), date(2026, 10, 31))  # mese in corso: da domani
    assert departure_window(3, date(2026, 10, 12)) == (date(2027, 3, 1), date(2027, 3, 31))  # mese passato: anno dopo
    assert departure_window(10, date(2026, 10, 31)) == (date(2027, 10, 1), date(2027, 10, 31))  # ultimo giorno del mese
    assert departure_window(12, date(2026, 10, 12)) == (date(2026, 12, 1), date(2026, 12, 31))

def test_planner_is_deterministic(world, session):
    _, first = run(world, session)
    _, second = run(world, session)
    assert first.model_dump() == second.model_dump()

def test_planner_never_writes(world, session):
    def totals():
        return (
            session.scalar(select(func.count()).select_from(Booking)),
            session.scalar(select(func.sum(Flight.seats_left))),
            session.scalar(select(func.count()).select_from(RoomAvailability).where(RoomAvailability.is_free)),
            session.scalar(select(func.sum(ActivityAvailability.spots_left))),
        )

    before = totals()
    run(world, session)
    assert not session.new and not session.dirty and not session.deleted
    assert totals() == before

def test_with_the_real_rag(world, session):
    """Integrazione: stesso planner, ma con le affinita' calcolate da Chroma."""
    index_activities(session, reset_collection())
    req = Requirements(**BASE)
    result = plan_trips(session, req, HOME, today=TODAY)  # ranker di default = RAG

    assert result.ok
    best = next(it for it in result.itineraries if "adatto" in it.label.lower())
    assert best.affinity > 0
    assert any(d.activity and d.activity.category in ("cultura", "relax") for d in best.days)
    check_itinerary(session, best, req)

# --- salvataggio della proposta ---------------------------------------------

def test_create_proposal_saves_the_itinerary_without_touching_availability(world, session):
    req, result = run(world, session)
    itinerary = result.itineraries[0]
    before = (
        session.scalar(select(func.sum(Flight.seats_left))),
        session.scalar(select(func.count()).select_from(RoomAvailability).where(RoomAvailability.is_free)),
        session.scalar(select(func.sum(ActivityAvailability.spots_left))),
    )

    booking = create_proposal(session, DEMO_USER_ID, None, itinerary)

    assert booking.status == "proposed" and booking.id is not None
    assert booking.travelers == req.travelers
    assert float(booking.total_cost) == pytest.approx(itinerary.costs.total, abs=0.01)

    # le righe figlie sono quelle dell'itinerario proposto
    session.expire(booking)
    assert [(f.direction, f.flight_id) for f in booking.flights] == [
        ("out", itinerary.flight_out.flight_id), ("return", itinerary.flight_return.flight_id)]
    assert [r.room_availability_id for r in booking.rooms] == [
        n.availability_id for room in itinerary.hotel.rooms for n in room.nights]
    assert [a.activity_availability_id for a in booking.activities] == [
        d.activity.availability_id for d in itinerary.days if d.activity]
    assert booking.city == itinerary.city and booking.hotel_id == itinerary.hotel.hotel_id

    after = (
        session.scalar(select(func.sum(Flight.seats_left))),
        session.scalar(select(func.count()).select_from(RoomAvailability).where(RoomAvailability.is_free)),
        session.scalar(select(func.sum(ActivityAvailability.spots_left))),
    )
    assert after == before

def test_new_proposal_discards_the_previous_one_in_the_same_conversation(world, session):
    _, result = run(world, session)
    first_it, second_it = result.itineraries[0], result.itineraries[1]
    chat, other_chat = Conversation(user_id=DEMO_USER_ID), Conversation(user_id=DEMO_USER_ID)
    session.add_all([chat, other_chat])
    session.flush()

    first = create_proposal(session, DEMO_USER_ID, chat.id, first_it)
    elsewhere = create_proposal(session, DEMO_USER_ID, other_chat.id, first_it)
    second = create_proposal(session, DEMO_USER_ID, chat.id, second_it)

    session.refresh(first)
    session.refresh(elsewhere)
    assert first.status == "discarded"
    assert second.status == "proposed"
    assert elsewhere.status == "proposed"  # un'altra chat non viene toccata

def test_saving_the_same_itinerary_twice_reuses_the_open_proposal(world, session):
    _, result = run(world, session)
    chat = Conversation(user_id=DEMO_USER_ID)
    session.add(chat)
    session.flush()

    first = create_proposal(session, DEMO_USER_ID, chat.id, result.itineraries[0])
    again = create_proposal(session, DEMO_USER_ID, chat.id, result.itineraries[0])

    assert again.id == first.id and first.status == "proposed"  # nessun duplicato, nessun 'discarded'
