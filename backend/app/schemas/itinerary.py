"""Schemi del planner: cosa entra (Requirements) e cosa esce (Itinerary o PlanningFailure).

Gli importi sono float arrotondati a 2 decimali: il planner calcola in Decimal e converte
solo qui, al confine con l'API/JSON.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings

class Requirements(BaseModel):
    """I dati che la chat raccoglie e valida prima di chiamare il planner."""

    budget: float = Field(gt=0, description="Budget totale in euro, per tutti i viaggiatori")
    country: str = Field(min_length=1)
    activities: list[str] = Field(min_length=1, description="Preferenze: categorie o testo libero")
    month: int = Field(ge=1, le=12, description="Mese di partenza (1-12)")
    departure_date: date | None = Field(default=None, description="Giorno di partenza esatto (facoltativo, deve cadere nel mese)")
    travelers: int = Field(default=1, ge=1, le=settings.max_travelers)
    nights: int = Field(default=settings.default_nights, ge=settings.min_nights, le=settings.max_nights)

class FlightLeg(BaseModel):
    flight_id: int
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    price_per_person: float

class RoomNight(BaseModel):
    availability_id: int  # riga di room_availability che la conferma segnera' come occupata
    night: date
    price: float  # per l'intera camera

class RoomStay(BaseModel):
    room_id: int
    name: str
    capacity: int
    nights: list[RoomNight]

class HotelStay(BaseModel):
    hotel_id: int
    name: str
    stars: int
    image_url: str | None = None  # foto dell'hotel (vedi db_scripts/fetch_hotel_photos.py)
    image_credit: str | None = None  # autore e licenza della foto
    rooms: list[RoomStay]  # le camere scelte, tutte libere per tutte le notti

class ActivityPick(BaseModel):
    availability_id: int  # riga di activity_availability che la conferma scalera'
    activity_id: int
    name: str
    category: str
    price_per_person: float
    affinity: float  # punteggio del RAG (piu' alto = piu' affine alle preferenze)

class ActivityDay(BaseModel):
    day: date
    activity: ActivityPick | None  # None = giorno libero (nessuna attivita' disponibile)

class CostBreakdown(BaseModel):
    flights: float
    hotel: float
    activities: float
    total: float

class Itinerary(BaseModel):
    label: str  # "Più adatto a te", "Più economico", "Alternativa"
    country: str
    city: str
    travelers: int
    nights: int
    departure_date: date
    return_date: date
    flight_out: FlightLeg
    flight_return: FlightLeg
    hotel: HotelStay
    days: list[ActivityDay]
    costs: CostBreakdown
    affinity: float  # somma dei punteggi delle attivita' scelte
    free_days: int  # giorni senza attivita' disponibile (li compila il planner)

class PlanningFailure(BaseModel):
    code: Literal["unknown_country", "no_flights", "no_hotel", "no_activities", "over_budget"]
    message: str
    # costo minimo di un itinerario completo che il planner sa costruire (solo over_budget)
    min_cost: float | None = None

class PlanResult(BaseModel):
    itineraries: list[Itinerary] = []
    failure: PlanningFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None
