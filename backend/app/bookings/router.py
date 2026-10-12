import logging

from fastapi import APIRouter, HTTPException, status

from app.auth.router import CurrentUser, DbSession
from app.bookings.schemas import BookingDetail, BookingOut
from app.models.models import Booking
from app.services import booking
from app.services.booking import BookingError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bookings", tags=["bookings"])


def descrivi(prenotazione: Booking) -> dict:
    """I campi di BookingOut di una prenotazione, letti dalle colonne di `bookings` e dal suo hotel."""
    return {
        "id": prenotazione.id, "status": prenotazione.status,
        "city": prenotazione.city, "country": prenotazione.country,
        "departure_date": prenotazione.departure_date, "return_date": prenotazione.return_date,
        "nights": prenotazione.nights, "travelers": prenotazione.travelers,
        "total_cost": float(prenotazione.total_cost),
        "hotel_name": prenotazione.hotel.name, "hotel_stars": prenotazione.hotel.stars,
        "hotel_image_url": getattr(prenotazione.hotel, "image_url", None),
    }


def trova(db: DbSession, id: int, user: CurrentUser) -> Booking:
    """La prenotazione dell'utente, oppure errore 404 (anche se esiste ma e' di un altro utente)."""
    try:
        return booking.get_booking(db, id, user.id)
    except BookingError as errore:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(errore))


@router.get("", response_model=list[BookingOut])
def elenco(user: CurrentUser, db: DbSession):
    """Le prenotazioni e le proposte dell'utente (non quelle sostituite), dalla piu' recente."""
    return [descrivi(p) for p in booking.user_bookings(db, user.id)]


@router.get("/{id}", response_model=BookingDetail)
def dettaglio(id: int, user: CurrentUser, db: DbSession):
    prenotazione = trova(db, id, user)
    return {**descrivi(prenotazione), "itinerary": booking.itinerary_of(prenotazione)}


@router.post("/{id}/confirm", response_model=BookingOut)
def conferma(id: int, user: CurrentUser, db: DbSession):
    """Conferma una proposta. Se qualcosa non e' piu' disponibile risponde 409 e non cambia nulla."""
    trova(db, id, user)
    try:
        prenotazione = booking.confirm_booking(db, id, user.id)
    except BookingError as errore:
        raise HTTPException(status.HTTP_409_CONFLICT, str(errore))
    db.commit()
    return descrivi(prenotazione)


@router.post("/{id}/cancel", response_model=BookingOut)
def annulla(id: int, user: CurrentUser, db: DbSession):
    """Annulla una prenotazione o una proposta; se era confermata libera di nuovo posti e camere."""
    trova(db, id, user)
    try:
        prenotazione = booking.cancel_booking(db, id, user.id)
    except BookingError as errore:
        raise HTTPException(status.HTTP_409_CONFLICT, str(errore))
    db.commit()
    return descrivi(prenotazione)
