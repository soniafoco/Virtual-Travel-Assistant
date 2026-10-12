"""RAG sulle attivita': indicizzazione in ChromaDB e ricerca per affinita'.

SQLite resta la fonte di verita' (prezzi, date, posti). Chroma e' un indice derivato:
contiene un documento per attivita', con lo stesso id di `activities.id`, e risponde
solo a "quali attivita' assomigliano a questa richiesta?". Disponibilita' e prezzi
si verificano poi in SQL.
"""

import logging
import os
import time
from functools import lru_cache

import chromadb
from chromadb.errors import NotFoundError
from chromadb.utils.embedding_functions import GoogleGenaiEmbeddingFunction
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Activity

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # quanti documenti si indicizzano per volta (limite dell'API di embedding di Gemini)

def min_affinity() -> float:
    """Sotto questo punteggio un'attivita' non c'entra con la richiesta; dipende dal modello di embedding."""
    return settings.min_affinity[settings.embedding_provider]

@lru_cache
def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_path)

@lru_cache
def _embedding_function():
    """Gemini (API) o Hugging Face (sentence-transformers in locale), secondo EMBEDDING_PROVIDER."""
    if settings.embedding_provider == "huggingface":
        # Import qui: con Gemini non serve caricare sentence-transformers (e torch).
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        if settings.hf_token:
            os.environ.setdefault("HF_TOKEN", settings.hf_token)  # huggingface_hub lo legge dall'ambiente

        # Carica il modello una sola volta (qualche secondo): poi resta in memoria.
        return SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
    # Chroma legge la chiave da una variabile d'ambiente; la nostra sta in settings (.env).
    os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    return GoogleGenaiEmbeddingFunction(model_name=settings.gemini_embedding_model, task_type=settings.gemini_embedding_task_type)

def _full_name(name: str) -> str:
    """Un provider diverso produce vettori di dimensione diversa: ognuno ha la sua collezione."""
    return f"{name}_{settings.embedding_provider}"

def get_collection(name: str = settings.chroma_collection):
    """La collezione delle attivita'. Metrica coseno esplicita: cosi' score = 1 - distanza."""
    return _client().get_or_create_collection(
        name=_full_name(name),
        embedding_function=_embedding_function(),
        configuration={"hnsw": {"space": "cosine"}},
    )

def precarica() -> None:
    """Carica subito il modello di embedding e l'indice, invece che alla prima ricerca di un utente.

    Il modello locale (Hugging Face) impiega qualche secondo a caricarsi: da chiamare all'avvio del server.
    Con Gemini non c'e' niente da caricare (gli embedding li calcola l'API): non facciamo nessuna chiamata.
    """
    inizio = time.time()
    collezione = get_collection()  # crea il client di Chroma e carica il modello di embedding

    if settings.embedding_provider == "huggingface":
        collezione.query(query_texts=["prova"], n_results=1)  # una ricerca di prova: il modello e' gia' pronto per la prima richiesta vera

    logger.info(
        "Indice vettoriale pronto: %d attivita' (embedding %s), %.1f secondi",
        collezione.count(), settings.embedding_provider, time.time() - inizio,
    )
    if collezione.count() == 0:
        logger.warning("L'indice vettoriale e' vuoto: lancia 'python -m scripts.index_vectors'")

def reset_collection(name: str = settings.chroma_collection):
    """Cancella e ricrea la collezione (serve se cambia il formato dei documenti)."""
    try:
        _client().delete_collection(_full_name(name))
    except NotFoundError:
        pass  # non esisteva ancora: nulla da cancellare
    return get_collection(name)

def activity_document(activity: Activity) -> str:
    """Il testo che diventa vettore. Categoria e target dentro il testo: cosi' una richiesta
    come "relax" o "con i bambini" ha un aggancio anche nel documento."""
    target = ", ".join(t for t in activity.target.split(",") if t)
    return f"{activity.name}. {activity.description} Categoria: {activity.category}. Ideale per: {target}."

def activity_metadata(activity: Activity) -> dict:
    """Metadata per filtrare (es. solo una nazione) prima della ricerca per somiglianza."""
    return {
        "country": activity.country,
        "city": activity.city,
        "category": activity.category,
        "target": activity.target,
    }

def index_activities(session: Session, collection=None) -> int:
    """Allinea Chroma a SQLite. Idempotente: rilanciarla non crea duplicati.

    Restituisce quanti documenti ci sono in Chroma dopo l'allineamento.
    """
    collection = collection or get_collection()
    activities = session.scalars(select(Activity)).all()

    # upsert = inserisce o aggiorna in base all'id. A gruppi: l'API di Gemini accetta al massimo 100 testi per richiesta
    for start in range(0, len(activities), BATCH_SIZE):
        group = activities[start:start + BATCH_SIZE]
        for attempt in range(4):
            try:
                collection.upsert(
                    ids=[str(a.id) for a in group],
                    documents=[activity_document(a) for a in group],
                    metadatas=[activity_metadata(a) for a in group],
                )
                break
            except ValueError as error:
                # il piano gratuito di Gemini permette 100 embedding al minuto: si aspetta e si riprova
                if "RESOURCE_EXHAUSTED" not in str(error) or attempt == 3:
                    raise
                logger.warning("Limite di richieste di embedding raggiunto: aspetto un minuto")
                time.sleep(65)

    # via dall'indice le attivita' che non esistono piu' in SQL
    current = {str(a.id) for a in activities}
    stale = [id_ for id_ in collection.get(include=[])["ids"] if id_ not in current]
    if stale:
        collection.delete(ids=stale)

    return collection.count()

def expand_preference(preference: str) -> str:
    """Una parola sola ("cultura") e' una richiesta povera per l'embedding: se la preferenza e' una categoria nota
    (config.yaml: category_queries) la sostituisce con una frase descrittiva. Il testo libero ("con i bambini") resta com'e'."""
    return settings.category_queries.get(preference.strip().lower(), preference.strip())

def rank_activities(
    preferences: list[str], country: str, n: int | None = None, collection=None
) -> list[tuple[int, float]]:
    """Attivita' della nazione ordinate per affinita' con le preferenze.

    Una ricerca per ogni preferenza, poi per ogni attivita' si tiene il punteggio migliore:
    cosi' con ["cultura", "relax"] sono rappresentate entrambe, invece di un vettore "medio".
    Restituisce [(activity_id, score), ...] dal piu' al meno affine. Senza `n` le restituisce
    tutte: il planner ha bisogno di un punteggio per ogni attivita' della nazione.
    """
    collection = collection or get_collection()
    n = n or max(collection.count(), 1)  # Chroma restituisce comunque solo quelle della nazione
    best: dict[int, float] = {}

    for preference in preferences:
        if not preference.strip():
            continue
        result = collection.query(
            query_texts=[expand_preference(preference)], n_results=n, where={"country": country}
        )
        # Chroma accetta piu' query insieme e risponde con liste annidate: noi ne facciamo una
        for id_, distance in zip(result["ids"][0], result["distances"][0]):
            score = 1 - distance
            best[int(id_)] = max(score, best.get(int(id_), score))

    return sorted(best.items(), key=lambda pair: pair[1], reverse=True)
