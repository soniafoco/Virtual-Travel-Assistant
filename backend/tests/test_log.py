"""Test dei log: richieste e risposte dell'API, con i segreti nascosti."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.logging import maschera, tronca
from app.main import app

@pytest.fixture
def client(db):
    return TestClient(app)

def test_secrets_are_hidden():
    assert maschera('{"email": "a@b.it", "password": "segreta1"}') == '{"email": "a@b.it", "password": "***"}'
    assert maschera("username=a%40b.it&password=segreta1") == "username=a%40b.it&password=***"
    assert maschera('{"access_token": "abc.def", "token_type": "bearer"}') == '{"access_token": "***", "token_type": "bearer"}'

def test_long_text_is_cut():
    testo = "x" * (settings.log_body_chars + 50)
    assert tronca(testo).endswith("... (+50 caratteri)")
    assert tronca("breve") == "breve"

def test_every_request_and_response_is_logged(client, caplog):
    with caplog.at_level("INFO", logger="app.http"):
        client.post("/api/auth/register", json={"name": "Sonia", "email": "s@example.com", "password": "password123"})
    log = caplog.text
    assert "INPUT  POST /api/auth/register" in log and "Sonia" in log
    assert "OUTPUT POST /api/auth/register -> 201" in log and '"email":"s@example.com"' in log
    assert "password123" not in log  # la password non finisce mai nel log

def test_login_token_is_not_logged(client, caplog):
    client.post("/api/auth/register", json={"name": "Sonia", "email": "s@example.com", "password": "password123"})
    with caplog.at_level("INFO", logger="app.http"):
        response = client.post("/api/auth/login", data={"username": "s@example.com", "password": "password123"})
    assert response.status_code == 200 and response.json()["access_token"]  # la risposta al client e' intatta
    assert response.json()["access_token"] not in caplog.text
    assert "password123" not in caplog.text

def test_errors_are_logged_with_their_status(client, caplog):
    with caplog.at_level("INFO", logger="app.http"):
        client.get("/api/auth/me")
    assert "OUTPUT GET /api/auth/me -> 401" in caplog.text

def test_docs_are_not_logged(client, caplog):
    with caplog.at_level("INFO", logger="app.http"):
        client.get("/openapi.json")
    assert "INPUT" not in caplog.text and "OUTPUT" not in caplog.text
