from fastapi import APIRouter, HTTPException, status

from app.auth.router import CurrentUser, DbSession
from app.conversations.schemas import ConversationDetail, ConversationOut
from app.models.models import Conversation
from app.schemas.itinerary import Itinerary

router = APIRouter(prefix="/conversations", tags=["conversations"])

TITOLO_MAX = 60  # caratteri del titolo


def titolo(conversazione: Conversation) -> str:
    """Il titolo di una chat e' l'inizio del primo messaggio dell'utente."""
    for messaggio in conversazione.messages:
        if messaggio.role == "user":
            testo = messaggio.content.strip()
            return testo if len(testo) <= TITOLO_MAX else testo[:TITOLO_MAX].rstrip() + "..."
    return "Chat senza titolo"


@router.get("", response_model=list[ConversationOut])
def elenco(user: CurrentUser):
    """Le chat dell'utente che hanno almeno un messaggio, dalla piu' recente."""
    risultato = []
    for conversazione in user.conversations:
        if not conversazione.messages:
            continue
        risultato.append({
            "id": conversazione.id, "title": titolo(conversazione),
            "last_message_at": conversazione.messages[-1].created_at,
            "messages_count": len(conversazione.messages),
        })
    risultato.sort(key=lambda c: c["last_message_at"], reverse=True)
    return risultato


@router.get("/{id}", response_model=ConversationDetail)
def dettaglio(id: int, user: CurrentUser, db: DbSession):
    conversazione = db.get(Conversation, id)
    if conversazione is None or conversazione.user_id != user.id:  # anche se esiste ma e' di un altro: 404
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversazione non trovata.")
    itinerari = [Itinerary.model_validate(it) for it in conversazione.requirements.get("itineraries", [])]
    return {"id": conversazione.id, "messages": conversazione.messages, "itineraries": itinerari}
