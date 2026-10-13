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

class RequirementsState(BaseModel):
    """I dati raccolti finora in una conversazione: tutti facoltativi, perche' all'inizio non c'e' niente.
    Si salva nella conversazione e si rimette nel prompt a ogni richiesta, cosi' l'agente non li dimentica."""

    budget: float | None = Field(default=None, gt=0)
    country: str | None = Field(default=None, min_length=1)
    activities: list[str] | None = Field(default=None, min_length=1)
    month: int | None = Field(default=None, ge=1, le=12)
    departure_date: date | None = None
    travelers: int | None = Field(default=None, ge=1, le=settings.max_travelers)
    nights: int | None = Field(default=None, ge=settings.min_nights, le=settings.max_nights)
    home_airport: str | None = Field(default=None, min_length=3, max_length=3)

    def missing(self) -> list[str]:
        """I dati obbligatori ancora vuoti (travelers, nights e departure_date hanno un default)."""
        mancanti = []
        for nome in ["budget", "country", "activities", "month", "home_airport"]:
            if getattr(self, nome) is None:
                mancanti.append(nome)
        return mancanti

    def to_requirements(self) -> Requirements:
        """I requisiti completi per il planner; viaggiatori e notti mancanti prendono il default di Requirements."""
        dati = {}
        for nome in ["budget", "country", "activities", "month", "departure_date", "travelers", "nights"]:
            if getattr(self, nome) is not None:
                dati[nome] = getattr(self, nome)
        return Requirements(**dati)

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
