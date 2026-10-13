"""Test delle chat precedenti: elenco e dettaglio, solo dell'utente collegato."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.models import Conversation, Message, User

@pytest.fixture
def mondo(db):
    """Un client autenticato come utente demo e un secondo utente."""
    from db_scripts.seed import seed
    seed(db, start=datetime(2026, 10, 12).date())
    db.add(User(email="altro@example.com", password_hash="x", name="Altro"))
    db.commit()
    client = TestClient(app)
    token = client.post("/api/auth/login", data={"username": "demo@example.com", "password": "demo1234"}).json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    return client

def crea_chat(db, user_id, *testi, giorno=1):
    chat = Conversation(user_id=user_id, requirements={})
    db.add(chat)
    db.flush()
    for i, testo in enumerate(testi):
        db.add(Message(conversation_id=chat.id, role="user" if i % 2 == 0 else "assistant", content=testo,
                       created_at=datetime(2026, 10, giorno, 10, i)))
    db.commit()
    return chat

def test_routes_require_login():
    client = TestClient(app)
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/conversations/1").status_code == 401

def test_list_is_newest_first_and_hides_empty_and_foreign_chats(mondo, db):
    vecchia = crea_chat(db, 1, "Vorrei andare in Spagna", "Bene!", giorno=1)
    nuova = crea_chat(db, 1, "Ciao", giorno=5)
    crea_chat(db, 1)  # senza messaggi: non si mostra
    altro = db.query(User).filter_by(email="altro@example.com").one().id
    crea_chat(db, altro, "Non e' tua")

    dati = mondo.get("/api/conversations").json()

    assert [c["id"] for c in dati] == [nuova.id, vecchia.id]
    assert dati[1]["title"] == "Vorrei andare in Spagna" and dati[1]["messages_count"] == 2

def test_long_titles_are_shortened(mondo, db):
    crea_chat(db, 1, "a" * 100)
    assert mondo.get("/api/conversations").json()[0]["title"] == "a" * 60 + "..."

def test_detail_has_the_messages_in_order(mondo, db):
    chat = crea_chat(db, 1, "uno", "due", "tre")
    dati = mondo.get(f"/api/conversations/{chat.id}").json()
    assert [(m["role"], m["content"]) for m in dati["messages"]] == [("user", "uno"), ("assistant", "due"), ("user", "tre")]
    assert dati["itineraries"] == []

def test_other_users_chat_is_not_found(mondo, db):
    altro = db.query(User).filter_by(email="altro@example.com").one().id
    chat = crea_chat(db, altro, "privata")
    assert mondo.get(f"/api/conversations/{chat.id}").status_code == 404
    assert mondo.get("/api/conversations/9999").status_code == 404
