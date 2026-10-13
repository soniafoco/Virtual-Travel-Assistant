"""Test del RAG: indicizzazione in Chroma e ricerca per affinita'.

Sono test di comportamento (chi sta in cima), non di punteggi esatti: i valori dipendono
dal modello di embedding.
"""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import Base, SessionLocal, engine
from app.models.models import Activity
from app.services.rag import (
    activity_document,
    expand_preference,
    get_collection,
    index_activities,
    rank_activities,
    reset_collection,
)
from db_scripts.seed import seed
from db_scripts.seed_data import ACTIVITIES, CATEGORIES

TOTALE_ATTIVITA = sum(len(lista) for lista in ACTIVITIES.values())

def _fresh_collection():
    """Una collezione con nome univoco: ogni test resta isolato dagli altri."""
    return get_collection(f"test_{uuid4().hex}")

@pytest.fixture(scope="module")
def index():
    """Seed completo + indicizzazione, una sola volta per tutto il modulo."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    collection = _fresh_collection()
    with SessionLocal() as session:
        seed(session, start=date(2026, 1, 1))
        total = index_activities(session, collection)
        activities = {a.id: a for a in session.scalars(select(Activity))}
    return SimpleNamespace(collection=collection, activities=activities, total=total)

def _top(index, preferences, country, k):
    ranked = rank_activities(preferences, country, collection=index.collection)
    return [index.activities[activity_id] for activity_id, _ in ranked[:k]]

# --- indicizzazione ---------------------------------------------------------

def test_every_activity_is_indexed(index):
    assert index.total == len(index.activities) == TOTALE_ATTIVITA
    assert index.collection.count() == TOTALE_ATTIVITA

def test_document_and_metadata_content(index):
    prado = next(a for a in index.activities.values() if a.name.startswith("Museo del Prado"))
    stored = index.collection.get(ids=[str(prado.id)])

    document = stored["documents"][0]
    assert document == activity_document(prado)
    assert prado.description in document
    assert "Categoria: cultura" in document
    assert "Ideale per: famiglie, coppie" in document
    assert stored["metadatas"][0] == {
        "country": "Spagna", "city": "Madrid", "category": "cultura", "target": "famiglie,coppie",
    }

def test_reindexing_does_not_create_duplicates(index):
    with SessionLocal() as session:
        assert index_activities(session, index.collection) == TOTALE_ATTIVITA
    assert index.collection.count() == TOTALE_ATTIVITA

def test_index_follows_sql_changes(db):
    """Un'attivita' modificata si aggiorna, una cancellata esce dall'indice."""
    collection = _fresh_collection()
    db.add_all([
        Activity(name="Tour A", country="Spagna", city="Madrid", category="cultura", price=10,
                 description="Primo testo.", target="famiglie"),
        Activity(name="Tour B", country="Spagna", city="Madrid", category="relax", price=10,
                 description="Secondo testo.", target="coppie"),
    ])
    db.commit()
    assert index_activities(db, collection) == 2

    first, second = db.scalars(select(Activity).order_by(Activity.id)).all()
    first.description = "Testo nuovo."
    db.delete(second)
    db.commit()

    assert index_activities(db, collection) == 1
    assert "Testo nuovo." in collection.get(ids=[str(first.id)])["documents"][0]

def test_reset_collection_works_even_if_it_does_not_exist():
    name = f"test_{uuid4().hex}"
    assert reset_collection(name).count() == 0  # la collezione non c'era: non deve dare errore

# --- ricerca ----------------------------------------------------------------

def test_results_belong_to_the_requested_country(index):
    for country in ("Spagna", "Portogallo", "Grecia", "Norvegia"):
        ranked = rank_activities(["relax e benessere"], country, collection=index.collection)
        in_country = [a for a in index.activities.values() if a.country == country]
        assert len(ranked) == len(in_country)
        assert all(index.activities[id_].country == country for id_, _ in ranked)

def test_scores_are_sorted_and_identical_text_scores_one(index):
    ranked = rank_activities(["cultura", "relax"], "Spagna", collection=index.collection)
    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True)

    prado = next(a for a in index.activities.values() if a.name.startswith("Museo del Prado"))
    best_id, best_score = rank_activities([activity_document(prado)], "Spagna", collection=index.collection)[0]
    assert best_id == prado.id
    assert best_score == pytest.approx(1.0, abs=1e-3)  # conferma la metrica coseno

def test_water_sports_query_finds_the_surf_course(index):
    top = _top(index, ["surf e sport acquatici"], "Spagna", 3)
    assert "Corso di surf e paddle alla Barceloneta" in [a.name for a in top]

def test_music_and_dancing_query_finds_nightlife(index):
    top = _top(index, ["serata di musica e ballo"], "Spagna", 2)
    assert {a.category for a in top} == {"nightlife"}

def test_children_query_favours_family_activities(index):
    top = _top(index, ["con i bambini"], "Spagna", 3)
    assert any("famiglie" in a.target for a in top)

def test_each_preference_is_represented(index):
    """Con piu' preferenze compaiono entrambe le categorie, non una via di mezzo."""
    for country in ("Spagna", "Portogallo", "Grecia", "Norvegia"):
        categories = {a.category for a in _top(index, ["cultura", "relax"], country, 4)}
        assert {"cultura", "relax"} <= categories, country

def test_asking_for_more_results_than_available_is_fine(index):
    spagna = sum(1 for a in index.activities.values() if a.country == "Spagna")  # le attivita' delle sue due citta'
    assert len(rank_activities(["relax"], "Spagna", n=500, collection=index.collection)) == spagna

def test_empty_or_unknown_requests_return_nothing(index):
    assert rank_activities([], "Spagna", collection=index.collection) == []
    assert rank_activities(["  "], "Spagna", collection=index.collection) == []
    assert rank_activities(["relax"], "Atlantide", collection=index.collection) == []

# --- espansione delle categorie ---------------------------------------------

def test_known_categories_are_expanded_and_free_text_is_not():
    assert set(settings.category_queries) == set(CATEGORIES)
    assert expand_preference(" Cultura ") == settings.category_queries["cultura"]
    assert expand_preference("con i bambini") == "con i bambini"

def test_precarica_loads_the_model_before_the_first_search():
    """All'avvio del server il modello di embedding e' gia' in memoria: la prima ricerca non lo carica."""
    from app.services import rag

    rag._embedding_function.cache_clear()
    assert rag._embedding_function.cache_info().currsize == 0
    rag.precarica()
    assert rag._embedding_function.cache_info().currsize == 1
