import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.router import get_current_user
from app.chat.schemas import ChatIn, ChatOut
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Booking, Conversation, Message, User
from app.schemas.itinerary import Itinerary, RequirementsState
from app.services.agent import build_agent, reply
from app.services.agent_tools import AgentContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("", response_model=ChatOut)
def chat(dati: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Un messaggio dell'utente: lo passa all'agente, salva la conversazione e restituisce la risposta."""

    # 1. Trovo la conversazione (deve essere dell'utente) oppure ne creo una nuova
    if dati.conversation_id is None:
        conversazione = Conversation(user_id=user.id, requirements={})
        db.add(conversazione)
        db.flush()  # assegna l'id
    else:
        conversazione = db.get(Conversation, dati.conversation_id)
        if conversazione is None or conversazione.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversazione non trovata.")

    # 2. Ricostruisco la cronologia dai messaggi salvati (solo gli ultimi, per non superare i limiti del modello) e aggiungo il nuovo
    storia = []
    for messaggio in conversazione.messages[-settings.chat_history_messages:]:
        storia.append({"role": messaggio.role, "content": messaggio.content})
    storia.append({"role": "user", "content": dati.message})
    db.add(Message(conversation_id=conversazione.id, role="user", content=dati.message))

    # 3. Preparo il contesto dell'agente. Ogni richiesta ne crea uno nuovo: gli ultimi itinerari proposti
    #    li recupero dalla conversazione, altrimenti "scelgo il numero 1" non saprebbe a cosa si riferisce
    contesto = AgentContext(db, user_id=user.id, conversation_id=conversazione.id)
    for itinerario in conversazione.requirements.get("itineraries", []):
        contesto.itineraries.append(Itinerary.model_validate(itinerario))

    # Anche i requisiti raccolti finora (budget, nazione, mese...): il modello li vede nel prompt a ogni richiesta
    contesto.state = RequirementsState.model_validate(conversazione.requirements.get("state", {}))

    # Anche l'ultima proposta salvata (quella che "conferma" deve prenotare) va ricavata dal database
    contesto.last_proposal_id = db.scalar(
        select(Booking.id)
        .where(Booking.conversation_id == conversazione.id, Booking.status == "proposed")
        .order_by(Booking.id.desc())
    )

    # 4. Chiedo la risposta all'agente. Se il modello non risponde annullo tutto (messaggio, proposte, prenotazioni)
    try:
        risposta = reply(build_agent(contesto), storia, session_id=str(conversazione.id))
    except Exception:
        db.rollback()
        logger.exception("L'agente non ha risposto (conversazione %s)", conversazione.id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "L'assistente non è disponibile al momento, riprova tra poco.")

    # 5. Salvo la risposta e gli ultimi itinerari della conversazione, poi confermo tutto insieme
    db.add(Message(conversation_id=conversazione.id, role="assistant", content=risposta))
    if contesto.itineraries_changed or contesto.state_changed:
        # Riassegno un dizionario nuovo (SQLAlchemy non vede le modifiche dentro un JSON) tenendo ciò che non è cambiato
        requisiti = dict(conversazione.requirements)
        if contesto.itineraries_changed:  # generate_itineraries ha sostituito la lista degli itinerari
            requisiti["itineraries"] = [it.model_dump(mode="json") for it in contesto.itineraries]
        if contesto.state_changed:  # un tool ha aggiornato i requisiti raccolti
            requisiti["state"] = contesto.state.model_dump(mode="json")
        conversazione.requirements = requisiti
    db.commit()

    return ChatOut(
        conversation_id=conversazione.id, reply=risposta,
        itineraries=contesto.itineraries if contesto.itineraries_changed and contesto.itineraries else None,
    )
