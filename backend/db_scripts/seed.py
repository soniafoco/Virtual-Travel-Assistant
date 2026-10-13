"""Popola il database con dati sintetici ma riproducibili.

Uso (da backend/):
    python -m db_scripts.seed

Cancella e ricrea tutte le tabelle, poi inserisce:
  - contenuto curato (citta', hotel, attivita': vedi seed_data.py)
  - disponibilita' e voli generati da regole con un generatore a seme fisso
"""

import random
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy import inspect, insert, select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.models import (
    Activity,
    ActivityAvailability,
    Flight,
    Hotel,
    Room,
    RoomAvailability,
    User,
)
from db_scripts.hotel_photos import carica_foto
from db_scripts.init_db import init_db
from db_scripts.seed_data import (
    ACTIVITIES,
    CITIES,
    DAYS,
    DEMO_DAYS,
    DEMO_USER,
    HOME_AIRPORTS,
    HOME_COUNTRY,
    HOTELS,
    ROOM_TYPES,
    SEASON,
)

DEPARTURE_HOURS = (6, 9, 13, 17, 20)
NO_FLIGHT_PROB = 0.12  # giorni in cui la tratta non ha voli
NO_ROOMS_PROB = 0.08  # notti in cui una camera e' occupata
ACTIVITY_DAY_PROB = 0.70  # giorni in cui l'attivita' e' disponibile

def _is_weekend(day: date) -> bool:
    return day.weekday() in (4, 5)  # venerdi' e sabato

def build_dataset(start: date, rng_seed: int = 42, num_days: int = DAYS) -> dict[str, list[dict]]:
    """Costruisce tutte le righe in memoria. Stessi (start, rng_seed) -> stessi dati."""
    rng = random.Random(rng_seed)
    days = [start + timedelta(days=i) for i in range(num_days)]

    photos = carica_foto()  # foto degli hotel (db_scripts/hotel_photos.json), se sono state scaricate
    hotels, base_price = [], {}
    for city in CITIES:
        for name, stars, price, description in HOTELS[city["city"]]:
            hotel_id = len(hotels) + 1
            base_price[hotel_id] = price
            hotels.append({
                "id": hotel_id, "name": name, "country": city["country"], "city": city["city"],
                "stars": stars, "description": description,
                "image_url": photos.get(name, {}).get("image_url"), "image_credit": photos.get(name, {}).get("image_credit"),
            })

    rooms, room_multiplier = [], {}
    for hotel in hotels:
        for type_name, capacity, multiplier, count in ROOM_TYPES:
            for number in range(1, count + 1):
                room_id = len(rooms) + 1
                room_multiplier[room_id] = multiplier
                rooms.append({
                    "id": room_id, "hotel_id": hotel["id"], "name": f"{type_name} {number}", "capacity": capacity,
                })

    # il fattore di una notte (stagione, variazione, weekend) e' lo stesso per tutte le camere dell'hotel
    night_factor = {}
    for hotel in hotels:
        for night in days:
            factor = SEASON[night.month] * rng.uniform(0.95, 1.05)
            night_factor[(hotel["id"], night)] = factor * (1.10 if _is_weekend(night) else 1.0)

    room_availability = []
    for room in rooms:
        base = base_price[room["hotel_id"]] * room_multiplier[room["id"]]
        for night in days:
            room_availability.append({
                "room_id": room["id"], "night": night,
                "price_per_night": round(base * night_factor[(room["hotel_id"], night)], 2),
                "is_free": rng.random() >= NO_ROOMS_PROB,
            })

    activities = []
    for city in CITIES:
        for name, category, price, target, description in ACTIVITIES[city["city"]]:
            activities.append({
                "id": len(activities) + 1, "name": name, "country": city["country"], "city": city["city"],
                "category": category, "price": price, "description": description, "target": target,
            })

    activity_availability = []
    for activity in activities:
        for day in days:
            if rng.random() < ACTIVITY_DAY_PROB:
                activity_availability.append({
                    "activity_id": activity["id"], "day": day, "spots_left": rng.randint(2, 20),
                })

    flights = []
    for origin, origin_factor in HOME_AIRPORTS.items():
        for city in CITIES:
            for day in days:
                for outbound in (True, False):
                    if rng.random() < NO_FLIGHT_PROB:
                        continue
                    departure = datetime.combine(day, time(rng.choice(DEPARTURE_HOURS)))
                    price = city["flight_base"] * origin_factor * SEASON[day.month] * rng.uniform(0.85, 1.25)
                    flights.append({
                        "origin_airport": origin if outbound else city["airport"],
                        "destination_airport": city["airport"] if outbound else origin,
                        "destination_country": city["country"] if outbound else HOME_COUNTRY,
                        "city": city["city"],
                        "departure": departure,
                        "arrival": departure + timedelta(hours=city["duration_h"]),
                        "price": round(price, 2),
                        "seats_left": 0 if rng.random() < 0.05 else rng.randint(2, 40),
                    })

    return {
        "hotels": hotels,
        "rooms": rooms,
        "room_availability": room_availability,
        "activities": activities,
        "activity_availability": activity_availability,
        "flights": flights,
    }

def seed(session: Session, start: date | None = None, rng_seed: int = 42, num_days: int = DAYS) -> dict[str, int]:
    """Inserisce i dati in tabelle vuote. Restituisce quante righe ha scritto per tabella."""
    data = build_dataset(start or date.today(), rng_seed, num_days)

    session.add(User(
        email=DEMO_USER["email"], password_hash=hash_password(DEMO_USER["password"]),
        name=DEMO_USER["name"],
    ))
    # insert(Modello) + lista di dizionari = inserimento di massa (molto piu' veloce di add() uno a uno)
    for model, key in (
        (Hotel, "hotels"),
        (Room, "rooms"),
        (RoomAvailability, "room_availability"),
        (Activity, "activities"),
        (ActivityAvailability, "activity_availability"),
        (Flight, "flights"),
    ):
        session.execute(insert(model), data[key])
    session.commit()

    return {"users": 1, **{key: len(rows) for key, rows in data.items()}}

def database_has_data() -> bool:
    """True se il database ha gia' degli hotel (cioe' e' gia' stato popolato)."""
    if not inspect(engine).has_table("hotels"):
        return False
    with SessionLocal() as session:
        return session.scalar(select(Hotel.id).limit(1)) is not None

if __name__ == "__main__":
    # reseed: false in config.yaml protegge i dati gia' presenti (utenti, chat, prenotazioni)
    if database_has_data() and not settings.reseed:
        print("Il database ha gia' dei dati: seed saltato. Per rifarlo da zero metti reseed: true in config.yaml.")
        sys.exit(0)
    init_db(reset=True)
    with SessionLocal() as session:
        counts = seed(session, num_days=DEMO_DAYS)
    print("Database popolato:")
    for table, n in counts.items():
        print(f"  {table:<22}{n:>7}")
    print(f"Utente demo: {DEMO_USER['email']} / {DEMO_USER['password']}")
