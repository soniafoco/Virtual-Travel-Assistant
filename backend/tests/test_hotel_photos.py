"""Test delle foto degli hotel: file delle foto, seed e itinerari."""

from datetime import date

from sqlalchemy import select

from app.models.models import Activity, Hotel
from app.schemas.itinerary import Requirements
from app.services import booking
from app.services.planner import plan_trips
from scripts.hotel_photos import carica_foto
from scripts.seed import seed
from scripts.seed_data import HOTELS

TODAY = date(2026, 10, 12)

def test_every_seed_hotel_has_a_photo_with_its_credit():
    foto = carica_foto()
    nomi = [nome for hotel in HOTELS.values() for nome, *_ in hotel]
    assert set(nomi) <= set(foto)
    for nome in nomi:
        assert foto[nome]["image_url"].startswith("https://")
        assert "Wikimedia Commons" in foto[nome]["image_credit"]  # autore e licenza della foto

def test_no_photo_is_used_for_two_hotels():
    pagine = [dati["pagina"] for dati in carica_foto().values()]
    assert len(pagine) == len(set(pagine))

def test_seed_saves_the_photos_in_the_hotels(db):
    seed(db, start=TODAY)
    hotel = db.scalars(select(Hotel).where(Hotel.name == "Gran Hotel Castellana")).one()
    assert hotel.image_url == carica_foto()["Gran Hotel Castellana"]["image_url"]
    assert all(h.image_url for h in db.scalars(select(Hotel)))

def test_the_photo_reaches_the_itinerary_and_the_saved_booking(db):
    seed(db, start=TODAY)

    def ranker(preferences, country):
        return [(a.id, 0.5) for a in db.scalars(select(Activity).where(Activity.country == country))]

    req = Requirements(budget=4000, country="Spagna", activities=["cultura"], month=11, travelers=2, nights=5)
    itinerario = plan_trips(db, req, "MXP", today=TODAY, ranker=ranker).itineraries[0]
    assert itinerario.hotel.image_url and itinerario.hotel.image_credit

    proposta = booking.create_proposal(db, 1, None, itinerario)
    db.flush()
    ricostruito = booking.itinerary_of(proposta)  # il dettaglio della dashboard
    assert ricostruito.hotel.image_url == itinerario.hotel.image_url
    assert ricostruito.hotel.image_credit == itinerario.hotel.image_credit
