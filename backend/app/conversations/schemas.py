from datetime import datetime

from pydantic import BaseModel

from app.schemas.itinerary import Itinerary

class ConversationOut(BaseModel):
    """Una chat nell'elenco delle chat precedenti."""

    id: int
    title: str  # l'inizio del primo messaggio dell'utente
    last_message_at: datetime
    messages_count: int

class MessageOut(BaseModel):
    role: str  # user | assistant
    content: str
    created_at: datetime

class ConversationDetail(BaseModel):
    """Una chat intera: i messaggi in ordine e gli ultimi itinerari proposti (per poterla riprendere)."""

    id: int
    messages: list[MessageOut]
    itineraries: list[Itinerary]
