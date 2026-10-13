from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))

    bookings: Mapped[list["Booking"]] = relationship(back_populates="user")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")

class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    country: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str] = mapped_column(String(80))
    stars: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")

    rooms: Mapped[list["Room"]] = relationship(back_populates="hotel")

class Room(Base):
    """Una camera fisica dell'hotel, con la sua capienza."""

    __tablename__ = "rooms"
    __table_args__ = (CheckConstraint("capacity >= 1", name="ck_rooms_capacity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))  # es. "Doppia 101"
    capacity: Mapped[int] = mapped_column(Integer)  # persone

    hotel: Mapped[Hotel] = relationship(back_populates="rooms")
    availabilities: Mapped[list["RoomAvailability"]] = relationship(back_populates="room")

class RoomAvailability(Base):
    """Una riga per camera e notte: il prezzo e se la camera e' ancora libera."""

    __tablename__ = "room_availability"
    __table_args__ = (UniqueConstraint("room_id", "night"),)  # un solo prezzo per camera e notte

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    night: Mapped[date] = mapped_column(Date, index=True)
    price_per_night: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # per l'intera camera
    is_free: Mapped[bool] = mapped_column(Boolean, default=True)

    room: Mapped[Room] = relationship(back_populates="availabilities")

class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    country: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40), index=True)  # cultura, sport, relax, nightlife...
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # a persona
    description: Mapped[str] = mapped_column(Text, default="")  # indicizzata anche nel vector DB
    target: Mapped[str] = mapped_column(String(120), default="")  # target ideali, es. "famiglie,giovani"

    availabilities: Mapped[list["ActivityAvailability"]] = relationship(back_populates="activity")

class ActivityAvailability(Base):
    __tablename__ = "activity_availability"
    __table_args__ = (
        UniqueConstraint("activity_id", "day"),  # una sola riga per attivita' e giorno
        CheckConstraint("spots_left >= 0", name="ck_activity_availability_spots_left"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("activities.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    spots_left: Mapped[int] = mapped_column(Integer)

    activity: Mapped[Activity] = relationship(back_populates="availabilities")

class Flight(Base):
    """Una tratta. Andata e ritorno sono due righe distinte."""

    __tablename__ = "flights"
    __table_args__ = (CheckConstraint("seats_left >= 0", name="ck_flights_seats_left"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    origin_airport: Mapped[str] = mapped_column(String(3), index=True)
    destination_airport: Mapped[str] = mapped_column(String(3), index=True)
    destination_country: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str] = mapped_column(String(80), index=True)  # citta' estera della tratta (andata e ritorno)
    departure: Mapped[datetime] = mapped_column(DateTime, index=True)
    arrival: Mapped[datetime] = mapped_column(DateTime)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # a persona
    seats_left: Mapped[int] = mapped_column(Integer)

class Booking(Base):
    """Un itinerario proposto o prenotato: i dati generali stanno qui, il dettaglio nelle tabelle figlie.

    Volo (andata e ritorno), camere+notti e attivita'+giorni stanno in `booking_flights`, `booking_rooms` e
    `booking_activities`, con la chiave esterna sulle righe di disponibilita': confermare/annullare
    significa togliere/rimettere su quelle righe. I prezzi sono quelli del momento della proposta.
    """

    __tablename__ = "bookings"
    __table_args__ = (CheckConstraint("travelers >= 1", name="ck_bookings_travelers"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True, default=None)
    # proposed -> confirmed -> cancelled
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    label: Mapped[str] = mapped_column(String(40))  # "Più adatto a te", "Più economico", "Alternativa"
    country: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(80))
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), index=True)
    travelers: Mapped[int] = mapped_column(Integer, default=1)
    nights: Mapped[int] = mapped_column(Integer)
    departure_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date] = mapped_column(Date)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="bookings")
    conversation: Mapped["Conversation | None"] = relationship(back_populates="bookings")
    hotel: Mapped[Hotel] = relationship()
    flights: Mapped[list["BookingFlight"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingFlight.id")
    rooms: Mapped[list["BookingRoom"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingRoom.id")
    activities: Mapped[list["BookingActivity"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingActivity.id")

class BookingFlight(Base):
    """Una tratta della prenotazione: direction e' 'out' (andata) o 'return' (ritorno)."""

    __tablename__ = "booking_flights"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    flight_id: Mapped[int] = mapped_column(ForeignKey("flights.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    price_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    booking: Mapped[Booking] = relationship(back_populates="flights")
    flight: Mapped[Flight] = relationship()

class BookingRoom(Base):
    """Una camera in una notte (una riga per camera e notte): occupa quella riga di room_availability."""

    __tablename__ = "booking_rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    room_availability_id: Mapped[int] = mapped_column(ForeignKey("room_availability.id"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # per l'intera camera

    booking: Mapped[Booking] = relationship(back_populates="rooms")
    room_availability: Mapped[RoomAvailability] = relationship()

class BookingActivity(Base):
    """Un'attivita' in un giorno: scala i posti di quella riga di activity_availability."""

    __tablename__ = "booking_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    activity_availability_id: Mapped[int] = mapped_column(ForeignKey("activity_availability.id"), index=True)
    price_per_person: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    affinity: Mapped[float] = mapped_column(Float)  # punteggio del RAG al momento della proposta

    booking: Mapped[Booking] = relationship(back_populates="activities")
    activity_availability: Mapped[ActivityAvailability] = relationship()

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # {"state": requisiti raccolti (RequirementsState), "itineraries": ultimi itinerari proposti}, vedi app/schemas/itinerary.py
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="conversations")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="conversation")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
