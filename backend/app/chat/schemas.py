from pydantic import BaseModel, Field

from app.schemas.itinerary import Itinerary

class ChatIn(BaseModel):
    conversation_id: int | None = None  # None = conversazione nuova
    message: str = Field(min_length=1, max_length=2000)

class ChatOut(BaseModel):
    conversation_id: int
    reply: str
    itineraries: list[Itinerary] | None = None  # solo se in questo messaggio sono stati (ri)generati
