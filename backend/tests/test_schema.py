"""Verifica che lo schema del database applichi davvero i vincoli decisi."""

from datetime import date, datetime

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.session import engine
from app.models.models import (
    Activity,
    ActivityAvailability,
    Booking,
    BookingFlight,
    Flight,
    Hotel,
    Room,
    RoomAvailability,
    User,
)

def _user(db) -> User:
    user = User(email="a@b.it", password_hash="x", name="Anna")
    db.add(user)
    db.flush()
    return user

def _room(db) -> Room:
    hotel = Hotel(name="H", country="Spagna", city="Madrid", stars=3)
    db.add(hotel)
    db.flush()
    room = Room(hotel_id=hotel.id, name="Doppia 1", capacity=2)
    db.add(room)
    db.flush()
    return room

def _room_night(db) -> RoomAvailability:
    night = RoomAvailability(room_id=_room(db).id, night=date(2026, 6, 1), price_per_night=80)
    db.add(night)
    db.flush()
    return night

def _flight(db) -> Flight:
    flight = Flight(
        origin_airport="MXP",
        destination_airport="MAD",
        destination_country="Spagna",
        city="Madrid",
        departure=datetime(2026, 6, 1, 8),
        arrival=datetime(2026, 6, 1, 10),
        price=100,
        seats_left=10,
    )
    db.add(flight)
    db.flush()
    return flight

def test_tables_and_new_columns(db):
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "users", "hotels", "rooms", "room_availability", "activities", "activity_availability",
        "flights", "bookings", "booking_flights", "booking_rooms", "booking_activities", "conversations", "messages",
    }
    booking_cols = {c["name"] for c in inspector.get_columns("bookings")}
    assert {"travelers", "city", "hotel_id", "departure_date"} <= booking_cols and "itinerary" not in booking_cols
    assert "room_capacity" not in {c["name"] for c in inspector.get_columns("hotels")}
    assert "capacity" in {c["name"] for c in inspector.get_columns("rooms")}
    assert "target" in {c["name"] for c in inspector.get_columns("activities")}

def test_room_night_is_unique(db):
    night = _room_night(db)
    db.add(RoomAvailability(room_id=night.room_id, night=night.night, price_per_night=90))
    with pytest.raises(IntegrityError):
        db.flush()

def test_room_is_free_by_default(db):
    assert _room_night(db).is_free is True

def test_activity_day_is_unique(db):
    activity = Activity(name="Tour", country="Spagna", city="Madrid", category="cultura", price=20)
    db.add(activity)
    db.flush()
    db.add(ActivityAvailability(activity_id=activity.id, day=date(2026, 6, 1), spots_left=5))
    db.flush()
    db.add(ActivityAvailability(activity_id=activity.id, day=date(2026, 6, 1), spots_left=3))
    with pytest.raises(IntegrityError):
        db.flush()

def test_foreign_keys_are_enforced(db):
    db.add(RoomAvailability(room_id=999, night=date(2026, 6, 1), price_per_night=80))
    with pytest.raises(IntegrityError):
        db.flush()

def test_counters_and_capacity_cannot_be_invalid(db):
    room = _room(db)
    room.capacity = 0
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    flight = _flight(db)
    flight.seats_left = -1
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    activity = Activity(name="Tour", country="Spagna", city="Madrid", category="cultura", price=20)
    db.add(activity)
    db.flush()
    db.add(ActivityAvailability(activity_id=activity.id, day=date(2026, 6, 1), spots_left=-1))
    with pytest.raises(IntegrityError):
        db.flush()

def _booking(db, **fields):
    hotel = Hotel(name="Hotel", country="Spagna", city="Madrid", stars=3)
    db.add(hotel)
    db.flush()
    values = dict(user_id=_user(db).id, hotel_id=hotel.id, label="Alternativa", country="Spagna", city="Madrid",
                  travelers=2, nights=7, departure_date=date(2026, 6, 1), return_date=date(2026, 6, 8), total_cost=500)
    values.update(fields)
    return Booking(**values)

def test_travelers_must_be_positive(db):
    db.add(_booking(db, travelers=0))
    with pytest.raises(IntegrityError):
        db.flush()

def test_booking_children_are_deleted_with_the_booking(db):
    flight = _flight(db)
    booking = _booking(db)
    booking.flights = [BookingFlight(flight_id=flight.id, direction="out", price_per_person=100)]
    db.add(booking)
    db.commit()
    assert db.scalar(select(func.count()).select_from(BookingFlight)) == 1

    db.delete(booking)
    db.commit()
    assert db.scalar(select(func.count()).select_from(BookingFlight)) == 0
