"""Verifica che i dati del seed abbiano le proprieta' che il planner si aspetta."""

from collections import defaultdict
from datetime import date

import pytest
from sqlalchemy import func, select

from app.auth.security import verify_password
from app.models.models import Hotel, User
from scripts.seed import build_dataset, seed
from scripts.seed_data import (
    CATEGORIES,
    CITIES,
    DAYS,
    DEMO_USER,
    HOME_AIRPORTS,
    HOME_COUNTRY,
    ROOM_TYPES,
    SEASON,
    TARGETS,
)

START = date(2026, 1, 1)

@pytest.fixture(scope="module")
def data():
    return build_dataset(START, rng_seed=42)

def test_same_seed_gives_same_data(data):
    assert build_dataset(START, rng_seed=42) == data

def test_different_seed_gives_different_data(data):
    assert build_dataset(START, rng_seed=7) != data

def test_sizes(data):
    assert len(data["hotels"]) == 36
    assert len(data["activities"]) == 168  # 14 per citta': anche un viaggio di 14 notti si riempie senza ripetizioni
    rooms_per_hotel = sum(count for _, _, _, count in ROOM_TYPES)
    assert len(data["rooms"]) == 36 * rooms_per_hotel
    assert len(data["room_availability"]) == len(data["rooms"]) * DAYS
    assert 0 < len(data["activity_availability"]) < 168 * DAYS  # alcuni giorni sono "buchi"
    assert len(data["flights"]) > 3_000

def test_every_country_covers_every_category(data):
    by_country = defaultdict(set)
    for activity in data["activities"]:
        by_country[activity["country"]].add(activity["category"])
    assert set(by_country) == {c["country"] for c in CITIES}
    for country, categories in by_country.items():
        assert categories == set(CATEGORIES), country

def test_targets_are_known(data):
    for activity in data["activities"]:
        assert set(activity["target"].split(",")) <= set(TARGETS), activity["name"]

def test_every_hotel_has_rooms_of_different_sizes(data):
    capacities = defaultdict(set)
    for room in data["rooms"]:
        capacities[room["hotel_id"]].add(room["capacity"])
    assert len(capacities) == 36
    assert all(sizes >= {2, 3, 4} for sizes in capacities.values())

def test_every_room_has_one_row_per_night(data):
    nights = defaultdict(list)
    for row in data["room_availability"]:
        nights[row["room_id"]].append(row["night"])
    assert len(nights) == len(data["rooms"])
    for room_id, room_nights in nights.items():
        assert len(room_nights) == len(set(room_nights)) == DAYS, room_id

def test_bigger_rooms_cost_more_than_doubles(data):
    price = {}  # (hotel, notte) -> prezzo per capienza
    room = {r["id"]: r for r in data["rooms"]}
    for row in data["room_availability"]:
        r = room[row["room_id"]]
        price.setdefault((r["hotel_id"], row["night"]), {})[r["capacity"]] = row["price_per_night"]
    assert all(p[4] > p[2] for p in price.values())

def test_every_route_has_both_directions(data):
    airports = {c["airport"]: c["country"] for c in CITIES}
    outbound = {(f["origin_airport"], f["destination_airport"]) for f in data["flights"]
                if f["origin_airport"] in HOME_AIRPORTS}
    back = {(f["origin_airport"], f["destination_airport"]) for f in data["flights"]
            if f["destination_airport"] in HOME_AIRPORTS}
    for home in HOME_AIRPORTS:
        for airport in airports:
            assert (home, airport) in outbound
            assert (airport, home) in back

def test_flight_details_are_consistent(data):
    country_of = {c["airport"]: c["country"] for c in CITIES}
    for f in data["flights"]:
        assert f["arrival"] > f["departure"]
        if f["origin_airport"] in HOME_AIRPORTS:
            assert f["destination_country"] == country_of[f["destination_airport"]]
        else:
            assert f["destination_country"] == HOME_COUNTRY

def test_flights_arrive_the_same_day_they_leave(data):
    # il planner conta le notti dal giorno di arrivo: con voli notturni date di partenza e arrivo non coinciderebbero
    assert all(f["arrival"].date() == f["departure"].date() for f in data["flights"])

def test_flight_city_matches_the_foreign_airport(data):
    city_of = {c["airport"]: c["city"] for c in CITIES}
    for f in data["flights"]:
        foreign = f["destination_airport"] if f["origin_airport"] in HOME_AIRPORTS else f["origin_airport"]
        assert f["city"] == city_of[foreign]

def test_prices_follow_the_season(data):
    by_month = defaultdict(list)
    for row in data["room_availability"]:
        by_month[row["night"].month].append(row["price_per_night"])
    average = {month: sum(prices) / len(prices) for month, prices in by_month.items()}
    # la finestra non copre l'anno intero: il prezzo diviso il fattore stagionale deve essere simile in ogni mese
    ratios = [average[month] / SEASON[month] for month in average]
    assert max(ratios) < min(ratios) * 1.15

def test_norway_flights_cost_more_than_spain(data):
    prices = defaultdict(list)
    for f in data["flights"]:
        if f["origin_airport"] in HOME_AIRPORTS:
            prices[f["destination_country"]].append(f["price"])
    average = {country: sum(p) / len(p) for country, p in prices.items()}
    assert average["Norvegia"] > average["Spagna"] * 1.5

def test_there_is_scarcity(data):
    assert any(not r["is_free"] for r in data["room_availability"])
    assert any(f["seats_left"] == 0 for f in data["flights"])

def test_seed_writes_everything_to_the_database(db):
    counts = seed(db, start=START)

    assert db.scalar(select(func.count()).select_from(Hotel)) == counts["hotels"] == 36
    demo = db.scalar(select(User).where(User.email == DEMO_USER["email"]))
    assert verify_password(DEMO_USER["password"], demo.password_hash)
    assert demo.password_hash != DEMO_USER["password"]
