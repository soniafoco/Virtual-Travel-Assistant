"""Test dell'agente: tool sul database seminato e ciclo agente con un modello finto (niente Gemini, niente Chroma)."""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.core.config import settings
from app.db.session import Base, SessionLocal, engine
from app.models.models import Activity, Booking
from app.services import agent_tools
from app.services.agent import build_agent, reply
from app.services.agent_tools import AgentContext, build_tools
from app.services.planner import plan_trips
from db_scripts.seed import seed

TODAY = date(2026, 10, 12)
HOME = "MXP"
DEMO_USER_ID = 1  # creato dal seed

PLAN_ARGS = dict(budget=2500, country="Spagna", activities=["cultura", "relax"], month=11, home_airport=HOME)

class FakeChat(GenericFakeChatModel):
    """Modello finto che recita risposte già scritte; bind_tools non cambia nulla."""

    def bind_tools(self, tools, **kwargs):
        return self

@pytest.fixture(scope="module")
def world():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    seed(session, start=TODAY)
    activities = [(a.id, a.country, a.category) for a in session.scalars(select(Activity))]
    yield SimpleNamespace(session=session, activities=activities)
    session.close()

@pytest.fixture
def ranker(world, monkeypatch):
    """Sostituisce il RAG con un ranker per categoria, sia nei tool sia nel planner."""

    def rank(preferences, country):
        scores = {
            activity_id: max(0.8 if category == p else 0.2 for p in preferences)
            for activity_id, activity_country, category in world.activities
            if activity_country == country
        }
        def per_punteggio(pair):
            return -pair[1]

        return sorted(scores.items(), key=per_punteggio)

    def pianifica(*a, **kw):
        return plan_trips(*a, **kw, ranker=rank)

    monkeypatch.setattr(agent_tools, "rank_activities", rank)
    monkeypatch.setattr(agent_tools, "plan_trips", pianifica)

@pytest.fixture
def ctx(world, ranker):
    yield AgentContext(world.session, user_id=DEMO_USER_ID, today=TODAY)
    world.session.rollback()

@pytest.fixture
def tools(ctx):
    return {t.name: t for t in build_tools(ctx)}

# --- tool -------------------------------------------------------------------

def test_destinations_list_countries_and_cities(tools):
    data = json.loads(tools["list_destinations"].invoke({}))
    assert "Spagna" in data and data["Spagna"]

def test_hotels_can_be_filtered_by_city(tools):
    city = json.loads(tools["list_destinations"].invoke({}))["Spagna"][0]
    hotels = json.loads(tools["list_hotels"].invoke({"country": "spagna", "city": city}))
    assert hotels and {h["citta"] for h in hotels} == {city}

def test_unknown_country_has_no_hotels(tools):
    assert tools["list_hotels"].invoke({"country": "Atlantide"}) == "Nessun hotel trovato."

def test_find_airport_translates_names_and_flags_served_airports(tools):
    data = json.loads(tools["find_airport"].invoke({"query": "fiumicino"}))
    assert [(a["codice"], a["voli_disponibili"]) for a in data] == [("FCO", True)]

def test_find_airport_returns_every_airport_of_a_city(tools):
    data = json.loads(tools["find_airport"].invoke({"query": "Milano"}))
    assert {a["codice"] for a in data} == {"MXP", "LIN"}
    assert {a["codice"]: a["voli_disponibili"] for a in data} == {"MXP": True, "LIN": False}

def test_find_airport_unknown_lists_served_airports(tools):
    data = json.loads(tools["find_airport"].invoke({"query": "Atlantide"}))
    assert data["aeroporti_con_voli"] == ["FCO", "MXP", "TRN"]

def test_flight_dates_stay_inside_the_requested_month(tools):
    data = json.loads(tools["list_flight_dates"].invoke({"home_airport": HOME, "country": "Spagna", "month": 11}))
    days = [d["giorno"] for city in data["citta"].values() for d in city]
    assert days and all(day.startswith("2026-11") for day in days)

def test_search_activities_returns_the_best_matches_first(tools):
    data = json.loads(tools["search_activities"].invoke({"country": "Spagna", "preferences": ["sport"]}))
    assert 0 < len(data) <= settings.max_activities
    assert data[0]["categoria"] == "sport"

def test_search_activities_drops_the_unrelated_ones(tools):
    data = json.loads(tools["search_activities"].invoke({"country": "Spagna", "preferences": ["sport"]}))
    assert {a["categoria"] for a in data} == {"sport"}  # il finto ranker da' 0.2 alle altre: sotto soglia

def test_search_activities_says_so_when_nothing_is_related(tools):
    answer = tools["search_activities"].invoke({"country": "Spagna", "preferences": ["fisica quantistica"]})
    assert answer.startswith("Nessuna attivita' in Spagna abbastanza affine")

def test_generate_itineraries_numbers_them_and_keeps_them_in_context(tools, ctx):
    data = json.loads(tools["generate_itineraries"].invoke(PLAN_ARGS))
    assert [it["numero"] for it in data] == list(range(1, len(data) + 1))
    assert len(ctx.itineraries) == len(data)
    assert all(it["costi_euro"]["total"] <= PLAN_ARGS["budget"] for it in data)

def test_generate_itineraries_explains_a_failure(tools, ctx):
    data = json.loads(tools["generate_itineraries"].invoke({**PLAN_ARGS, "budget": 50}))
    assert data["errore"] == "over_budget" and data["costo_minimo"] > 50
    assert ctx.itineraries == []

def test_generate_itineraries_reports_invalid_data_to_the_model(tools):
    result = tools["generate_itineraries"].invoke({**PLAN_ARGS, "month": 13})
    assert result.startswith("Dati non validi") and "month" in result

def test_save_proposal_stores_the_chosen_itinerary(tools, ctx, world):
    tools["generate_itineraries"].invoke(PLAN_ARGS)
    saved = json.loads(tools["save_proposal"].invoke({"itinerary_number": 1}))
    booking = world.session.get(Booking, saved["proposta_salvata"])
    assert booking.status == "proposed" and booking.user_id == DEMO_USER_ID
    assert float(booking.total_cost) == pytest.approx(ctx.itineraries[0].costs.total)

def test_save_proposal_rejects_numbers_never_shown(tools):
    assert "Numero non valido" in tools["save_proposal"].invoke({"itinerary_number": 1})

def test_save_proposal_needs_a_user(world, ranker):
    anonymous = {t.name: t for t in build_tools(AgentContext(world.session, today=TODAY))}
    anonymous["generate_itineraries"].invoke(PLAN_ARGS)
    assert "autenticato" in anonymous["save_proposal"].invoke({"itinerary_number": 1})

# --- agente -----------------------------------------------------------------

def test_agent_calls_the_planner_tool_and_answers(ctx):
    script = iter([
        AIMessage(content="", tool_calls=[{"name": "generate_itineraries", "args": PLAN_ARGS, "id": "call-1"}]),
        AIMessage(content="Ecco i tuoi itinerari."),
    ])
    agent = build_agent(ctx, FakeChat(messages=script))

    answer = reply(agent, [{"role": "user", "content": "Voglio andare in Spagna a novembre con 2500 euro"}])

    assert answer == "Ecco i tuoi itinerari."
    assert ctx.itineraries  # il tool e' stato eseguito davvero sul database

# --- log ----------------------------------------------------------------------

def test_agent_logs_every_step(world, ranker, caplog):
    """Il log contiene l'input e l'output del modello e di ogni tool, senza chiamare un LLM vero."""
    call = AIMessage(content="", tool_calls=[{"name": "list_destinations", "args": {}, "id": "1"}])
    answer = AIMessage(content="Abbiamo diverse destinazioni.")
    agent = build_agent(AgentContext(world.session, user_id=DEMO_USER_ID, today=TODAY), FakeChat(messages=iter([call, answer])))

    with caplog.at_level("INFO", logger="app.agent"):
        reply(agent, [{"role": "user", "content": "Dove posso andare?"}])

    log = caplog.text
    assert "LLM INPUT" in log and "Dove posso andare?" in log
    assert "LLM OUTPUT" in log and "list_destinations" in log
    assert "TOOL INPUT  list_destinations" in log and "TOOL OUTPUT list_destinations" in log
    assert "Abbiamo diverse destinazioni." in log
