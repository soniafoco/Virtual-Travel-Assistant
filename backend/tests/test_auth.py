"""Test dell'autenticazione: registrazione, login (modulo OAuth2) e route protette."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.security import ALGORITHM
from app.core.config import settings
from app.main import app

NEW_USER = {"name": "Sonia", "email": "Sonia@Example.com", "password": "password123"}

@pytest.fixture
def client(db):  # `db` ricrea lo schema vuoto prima di ogni test
    return TestClient(app)

def register(client, **changes):
    return client.post("/api/auth/register", json={**NEW_USER, **changes})

def login(client, email="sonia@example.com", password="password123"):
    # login OAuth2 standard: modulo (non JSON), l'email va nel campo `username`
    return client.post("/api/auth/login", data={"username": email, "password": password})

def bearer(token):
    return {"Authorization": f"Bearer {token}"}

def test_register_creates_the_user_without_exposing_the_password(client):
    response = register(client)
    assert response.status_code == 201
    assert response.json() == {"id": 1, "name": "Sonia", "email": "sonia@example.com"}  # email normalizzata

def test_register_twice_with_the_same_email_conflicts(client):
    register(client)
    assert register(client, email="SONIA@example.com").status_code == 409

def test_register_validates_the_input(client):
    assert register(client, password="corta").status_code == 422
    assert register(client, email="non-una-email").status_code == 422
    assert register(client, name="").status_code == 422

def test_register_refuses_blank_names_and_passwords_that_bcrypt_cannot_hash(client):
    assert register(client, name="   ").status_code == 422
    assert register(client, password=" " * 8).status_code == 422
    assert register(client, password="è" * 40).status_code == 422  # 40 caratteri ma 80 byte

def test_login_with_a_password_over_72_bytes_is_refused_not_an_error(client):
    register(client)
    assert login(client, password="è" * 40).status_code == 401

def test_login_returns_a_bearer_token(client):
    register(client)
    response = login(client, email="SONIA@example.com")  # l'email non distingue maiuscole
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer" and response.json()["access_token"]

def test_wrong_password_and_unknown_email_look_the_same(client):
    register(client)
    wrong = login(client, password="sbagliata")
    unknown = login(client, email="nessuno@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()

def test_me_returns_the_logged_user(client):
    register(client)
    token = login(client).json()["access_token"]
    response = client.get("/api/auth/me", headers=bearer(token))
    assert response.status_code == 200 and response.json()["email"] == "sonia@example.com"

def test_me_requires_a_token(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"

def test_me_rejects_a_forged_or_expired_token(client):
    register(client)
    forged = jwt.encode({"sub": "1"}, "un-altro-segreto", algorithm=ALGORITHM)
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, settings.secret_key, algorithm=ALGORITHM
    )
    for token in (forged, expired, "non-un-token"):
        assert client.get("/api/auth/me", headers=bearer(token)).status_code == 401

def test_token_of_a_deleted_user_is_rejected(client, db):
    register(client)
    token = login(client).json()["access_token"]
    db.execute(text("DELETE FROM users"))
    db.commit()
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 401
