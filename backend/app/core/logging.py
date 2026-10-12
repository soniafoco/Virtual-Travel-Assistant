import logging
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request, Response

from app.core.config import settings

logger = logging.getLogger("app.http")

# Pagine di documentazione di FastAPI: non servono nei log
PERCORSI_IGNORATI = ("/docs", "/redoc", "/openapi.json")


def setup_logging() -> None:
    """Scrive i log su file (con rotazione) e a console. Da chiamare una volta all'avvio."""
    path = Path(settings.log_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    handlers = [
        RotatingFileHandler(
            path, maxBytes=settings.log_max_bytes, backupCount=settings.log_backup_count, encoding="utf-8",
        ),
        logging.StreamHandler(),
    ]
    logging.basicConfig(level=settings.log_level.upper(), format=settings.log_format, handlers=handlers, force=True)

    # Le librerie esterne scrivono troppi messaggi di servizio: li mostro solo se sono avvisi o errori
    for nome in ("watchfiles", "httpx", "httpx2", "httpcore", "urllib3", "chromadb", "sentence_transformers", "multipart"):
        logging.getLogger(nome).setLevel(logging.WARNING)


def maschera(testo: str) -> str:
    """Nasconde password e token, sia nei JSON ("password": "abc") sia nei moduli (password=abc)."""
    testo = re.sub(r'("(?:password|access_token)"\s*:\s*")[^"]*(")', r"\1***\2", testo)
    testo = re.sub(r"((?:^|&)password=)[^&]*", r"\1***", testo)
    return testo


def tronca(testo) -> str:
    """Accorcia i testi lunghi (settings.log_body_chars), indicando quanti caratteri mancano."""
    testo = str(testo)
    massimo = settings.log_body_chars
    if len(testo) > massimo:
        return testo[:massimo] + "... (+" + str(len(testo) - massimo) + " caratteri)"
    return testo


async def log_richieste(request: Request, call_next):
    """Middleware: scrive nel log l'input (richiesta) e l'output (risposta) di ogni chiamata all'API."""
    if request.url.path in PERCORSI_IGNORATI:
        return await call_next(request)

    inizio = time.time()

    # Input: metodo, indirizzo, parametri e corpo della richiesta (con password e token nascosti)
    corpo = (await request.body()).decode("utf-8", errors="replace")
    logger.info(
        "INPUT  %s %s | query: %s | corpo: %s",
        request.method, request.url.path, request.url.query or "-", tronca(maschera(corpo)) or "-",
    )

    try:
        risposta = await call_next(request)
    except Exception:
        logger.exception("ERRORE non gestito in %s %s", request.method, request.url.path)
        raise

    # Output: il corpo della risposta arriva a pezzi; lo leggo tutto e poi ricostruisco la risposta da restituire
    pezzi = [pezzo async for pezzo in risposta.body_iterator]
    corpo_risposta = b"".join(pezzi)
    durata = (time.time() - inizio) * 1000
    logger.info(
        "OUTPUT %s %s -> %s (%.0f ms) | corpo: %s",
        request.method, request.url.path, risposta.status_code, durata,
        tronca(maschera(corpo_risposta.decode("utf-8", errors="replace"))) or "-",
    )

    return Response(
        content=corpo_risposta, status_code=risposta.status_code,
        headers=dict(risposta.headers), media_type=risposta.media_type,
    )
