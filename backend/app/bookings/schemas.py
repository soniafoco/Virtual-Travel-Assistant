from datetime import date

from pydantic import BaseModel

from app.schemas.itinerary import Itinerary

class BookingOut(BaseModel):
    """Una prenotazione nell'elenco della dashboard: i dati principali, ricavati dall'itinerario salvato."""

    id: int
    status: str  # proposed | confirmed | cancelled
    city: str
    country: str
    departure_date: date
    return_date: date
    nights: int
    travelers: int
    total_cost: float
    hotel_name: str
    hotel_stars: int
    hotel_image_url: str | None = None

class BookingDetail(BookingOut):
    """Il dettaglio di una prenotazione: in piu' l'itinerario completo (voli, hotel, giorno per giorno)."""

    itinerary: Itinerary
