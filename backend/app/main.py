import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.auth.router import router as auth_router
from app.bookings.router import router as bookings_router
from app.chat.router import router as chat_router
from app.conversations.router import router as conversations_router
from app.core.config import settings
from app.core.logging import log_richieste, setup_logging
from app.core.tracing import setup_tracing
from app.db.session import Base, engine
from app.models import models
from app.services.rag import precarica

# Avvia logs e traces su Phoenix
setup_logging()
setup_tracing()

# Crea tabelle nel db se non esistono
Base.metadata.create_all(engine)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    """Eseguita all'avvio del server (prima della prima richiesta): carica i modelli una volta sola."""
    try:
        precarica()
    except Exception:
        # Se l'indice non e' disponibile il server parte lo stesso: ogni ricerca riprovera' a caricarlo
        logger.exception("Precarica dei modelli non riuscita")
    yield


app = FastAPI(title="Virtual Travel Assistant", lifespan=lifespan) 

app.middleware("http")(log_richieste)  # scrive nel log ogni richiesta e ogni risposta

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return RedirectResponse("/docs")  # il backend e' solo un'API: rimanda alla documentazione

@app.get("/api/health")
def health():
    return {"status": "ok"}

app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(bookings_router, prefix="/api")