"""Test dell'endpoint chat: conversazione salvata nel database, itinerari ricordati tra un messaggio e l'altro."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.session import Base, SessionLocal, engine
from app.models.models import Activity, Booking, Conversation, Message, User
from app.main import app
from app.services import agent, agent_tools
from app.services.planner import plan_trips
from db_scripts.seed import seed

TODAY = date(2026, 10, 12)

class FakeChat(GenericFakeChatModel):
    """Modello finto che recita risposte già scritte; bind_tools non cambia nulla."""

    def bind_tools(self, tools, **kwargs):
        return self

def tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "1"}])

PLAN_ARGS = dict(budget=3000, country="Spagna", activities=["cultura"], month=11, home_airport="MXP", travelers=2, nights=5)

@pytest.fixture
def mondo(db, monkeypatch):
    """Database seminato, ranking senza RAG, data fissa e un client già autenticato come utente demo."""
    seed(db, start=TODAY)
    db.commit()

    def ranker(preferences, country):
        return [(a.id, 0.5) for a in db.scalars(select(Activity).where(Activity.country == country))]

    def pianifica(*a, **kw):
        return plan_trips(*a, **{**kw, "today": TODAY}, ranker=ranker)

    monkeypatch.setattr(agent_tools, "rank_activities", ranker)
    monkeypatch.setattr(agent_tools, "plan_trips", pianifica)

    client = TestClient(app)
    token = client.post("/api/auth/login", data={"username": "demo@example.com", "password": "demo1234"}).json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    return client

def modello_finto(monkeypatch, *turni):
    """Ogni messaggio dell'utente usa il copione successivo: una lista di risposte del modello."""
    copioni = iter(turni)
    def costruisci(provider=None):
        return FakeChat(messages=iter(next(copioni)))

    monkeypatch.setattr(agent, "build_model", costruisci)

def test_chat_requires_login():
    assert TestClient(app).post("/api/chat", json={"message": "ciao"}).status_code == 401

def test_chat_creates_a_conversation_and_saves_the_messages(mondo, monkeypatch, db):
    modello_finto(monkeypatch, [AIMessage(content="Ciao! Dove vuoi andare?")])
    risposta = mondo.post("/api/chat", json={"message": "Ciao"})

    assert risposta.status_code == 200
    dati = risposta.json()
    assert dati["reply"] == "Ciao! Dove vuoi andare?" and dati["itineraries"] is None
    db.expire_all()
    messaggi = db.scalars(select(Message).where(Message.conversation_id == dati["conversation_id"])).all()
    assert [(m.role, m.content) for m in messaggi] == [("user", "Ciao"), ("assistant", "Ciao! Dove vuoi andare?")]

def test_the_conversation_continues_with_its_id(mondo, monkeypatch, db):
    modello_finto(monkeypatch, [AIMessage(content="Prima risposta")], [AIMessage(content="Seconda risposta")])
    primo = mondo.post("/api/chat", json={"message": "uno"}).json()
    secondo = mondo.post("/api/chat", json={"conversation_id": primo["conversation_id"], "message": "due"}).json()

    assert secondo["conversation_id"] == primo["conversation_id"]
    db.expire_all()
    assert db.scalar(select(Message.id).where(Message.conversation_id == primo["conversation_id"]).order_by(Message.id.desc())) == 4

def test_a_conversation_of_another_user_is_not_found(mondo, db):
    altro = User(email="altro@example.com", password_hash="x", name="Altro")
    db.add(altro)
    db.flush()
    altra_conversazione = Conversation(user_id=altro.id, requirements={})
    db.add(altra_conversazione)
    db.commit()
    altra = altra_conversazione.id
    assert mondo.post("/api/chat", json={"conversation_id": altra, "message": "ciao"}).status_code == 404

def test_empty_or_too_long_messages_are_refused(mondo):
    assert mondo.post("/api/chat", json={"message": ""}).status_code == 422
    assert mondo.post("/api/chat", json={"message": "x" * 2001}).status_code == 422

def test_itineraries_survive_between_messages_up_to_the_booking(mondo, monkeypatch, db):
    modello_finto(
        monkeypatch,
        [tool_call("generate_itineraries", **PLAN_ARGS), AIMessage(content="Ecco gli itinerari.")],
        [tool_call("save_proposal", itinerary_number=1), AIMessage(content="Proposta salvata, vuoi confermarla?")],
        [tool_call("confirm_booking"), AIMessage(content="Prenotazione confermata!")],
    )

    # 1. generazione: la risposta contiene gli itinerari per le schede del frontend
    primo = mondo.post("/api/chat", json={"message": "Voglio andare in Spagna"}).json()
    assert primo["itineraries"] and primo["itineraries"][0]["city"]
    chat_id = primo["conversation_id"]

    # 2. scelta: e' un messaggio NUOVO (contesto nuovo), ma l'agente ricorda gli itinerari della conversazione
    secondo = mondo.post("/api/chat", json={"conversation_id": chat_id, "message": "Prendo il primo"}).json()
    assert secondo["itineraries"] is None
    db.expire_all()
    prenotazione = db.scalars(select(Booking)).one()
    assert prenotazione.status == "proposed" and prenotazione.conversation_id == chat_id

    # 3. conferma
    mondo.post("/api/chat", json={"conversation_id": chat_id, "message": "Si, conferma"})
    db.expire_all()
    assert db.scalars(select(Booking)).one().status == "confirmed"

def test_a_model_failure_changes_nothing(mondo, monkeypatch, db):
    class Rotto(FakeChat):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("quota esaurita")

    def costruisci(provider=None):
        return Rotto(messages=iter([]))

    monkeypatch.setattr(agent, "build_model", costruisci)
    risposta = mondo.post("/api/chat", json={"message": "ciao"})

    assert risposta.status_code == 502
    db.expire_all()
    assert db.scalars(select(Message)).all() == [] and db.scalars(select(Conversation)).all() == []
