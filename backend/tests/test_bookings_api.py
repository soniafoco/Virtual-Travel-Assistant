"""Test degli endpoint delle prenotazioni (la dashboard)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.models import Activity, Booking, RoomAvailability, User
from app.schemas.itinerary import Requirements
from app.services import booking
from app.services.planner import plan_trips
from db_scripts.seed import seed

TODAY = date(2026, 10, 12)

@pytest.fixture
def mondo(db):
    """Database seminato, un client autenticato come utente demo e un secondo utente."""
    seed(db, start=TODAY)
    db.add(User(email="altro@example.com", password_hash="x", name="Altro"))
    db.commit()
    client = TestClient(app)
    token = client.post("/api/auth/login", data={"username": "demo@example.com", "password": "demo1234"}).json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    return client

def crea_proposta(db, user_id=1):
    """Salva una proposta per l'utente e restituisce la prenotazione."""

    def ranker(preferences, country):  # senza RAG: tutte le attivita' della nazione con lo stesso punteggio
        return [(a.id, 0.5) for a in db.scalars(select(Activity).where(Activity.country == country))]

    req = Requirements(budget=4000, country="Spagna", activities=["cultura"], month=11, travelers=2, nights=5)
    itinerario = plan_trips(db, req, "MXP", today=TODAY, ranker=ranker).itineraries[0]
    proposta = booking.create_proposal(db, user_id, None, itinerario)
    db.commit()
    return proposta

def test_all_routes_require_login():
    client = TestClient(app)
    assert client.get("/api/bookings").status_code == 401
    assert client.get("/api/bookings/1").status_code == 401
    assert client.post("/api/bookings/1/confirm").status_code == 401
    assert client.post("/api/bookings/1/cancel").status_code == 401

def test_list_is_empty_without_bookings(mondo):
    assert mondo.get("/api/bookings").json() == []

def test_list_shows_my_bookings_newest_first(mondo, db):
    prima = crea_proposta(db)
    seconda = crea_proposta(db)  # senza conversazione la prima non viene scartata

    dati = mondo.get("/api/bookings").json()

    assert [p["id"] for p in dati] == [seconda.id, prima.id]
    primo = dati[0]
    assert primo["status"] == "proposed" and primo["city"] and primo["hotel_name"] and primo["travelers"] == 2
    assert set(primo) == {
        "id", "status", "city", "country", "departure_date", "return_date", "nights", "travelers",
        "total_cost", "hotel_name", "hotel_stars", "hotel_image_url",
    }

def test_list_hides_replaced_proposals_and_other_users_bookings(mondo, db):
    visibile = crea_proposta(db)
    sostituita = crea_proposta(db)
    sostituita.status = "discarded"
    altro = db.scalar(select(User.id).where(User.email == "altro@example.com"))
    crea_proposta(db, user_id=altro)
    db.commit()

    assert [p["id"] for p in mondo.get("/api/bookings").json()] == [visibile.id]

def test_detail_has_the_full_itinerary(mondo, db):
    proposta = crea_proposta(db)
    dati = mondo.get(f"/api/bookings/{proposta.id}").json()
    assert dati["id"] == proposta.id
    assert dati["itinerary"]["hotel"]["name"] == dati["hotel_name"]
    assert len(dati["itinerary"]["days"]) == 5 and dati["itinerary"]["flight_out"]["flight_id"]

def test_other_users_booking_is_not_found(mondo, db):
    altro = db.scalar(select(User.id).where(User.email == "altro@example.com"))
    sua = crea_proposta(db, user_id=altro)
    for risposta in (
        mondo.get(f"/api/bookings/{sua.id}"),
        mondo.post(f"/api/bookings/{sua.id}/confirm"),
        mondo.post(f"/api/bookings/{sua.id}/cancel"),
    ):
        assert risposta.status_code == 404
    db.expire_all()
    assert db.get(Booking, sua.id).status == "proposed"  # nessuno l'ha toccata

def test_confirm_then_cancel(mondo, db):
    proposta = crea_proposta(db)

    confermata = mondo.post(f"/api/bookings/{proposta.id}/confirm")
    assert confermata.status_code == 200 and confermata.json()["status"] == "confirmed"
    db.expire_all()
    assert db.get(Booking, proposta.id).status == "confirmed"  # la route ha fatto il commit

    annullata = mondo.post(f"/api/bookings/{proposta.id}/cancel")
    assert annullata.status_code == 200 and annullata.json()["status"] == "cancelled"
    db.expire_all()
    assert db.get(Booking, proposta.id).status == "cancelled"

def test_confirm_conflicts_when_a_room_was_taken(mondo, db):
    proposta = crea_proposta(db)
    camera = proposta.rooms[0].room_availability_id
    db.get(RoomAvailability, camera).is_free = False
    db.commit()

    risposta = mondo.post(f"/api/bookings/{proposta.id}/confirm")

    assert risposta.status_code == 409 and "non e' piu' libera" in risposta.json()["detail"]
    db.expire_all()
    assert db.get(Booking, proposta.id).status == "proposed"  # la proposta resta com'era

def test_confirm_twice_and_cancel_twice_conflict(mondo, db):
    proposta = crea_proposta(db)
    mondo.post(f"/api/bookings/{proposta.id}/confirm")
    assert mondo.post(f"/api/bookings/{proposta.id}/confirm").status_code == 409
    mondo.post(f"/api/bookings/{proposta.id}/cancel")
    assert mondo.post(f"/api/bookings/{proposta.id}/cancel").status_code == 409

def test_unknown_booking_is_not_found(mondo):
    assert mondo.get("/api/bookings/999").status_code == 404

def test_detail_rebuilds_the_itinerary_that_the_planner_proposed(mondo, db):
    """L'itinerario ricostruito dalle righe salvate coincide con quello originale del planner."""

    def ranker(preferences, country):
        return [(a.id, 0.5) for a in db.scalars(select(Activity).where(Activity.country == country))]

    req = Requirements(budget=4000, country="Spagna", activities=["cultura"], month=11, travelers=2, nights=5)
    originale = plan_trips(db, req, "MXP", today=TODAY, ranker=ranker).itineraries[0]
    proposta = booking.create_proposal(db, 1, None, originale)
    db.commit()

    ricostruito = mondo.get(f"/api/bookings/{proposta.id}").json()["itinerary"]

    atteso = originale.model_dump(mode="json")
    for campo in ("affinity",):  # somma di punteggi arrotondata in modo diverso: non serve alla dashboard
        atteso.pop(campo)
        ricostruito.pop(campo)
    assert ricostruito == atteso
