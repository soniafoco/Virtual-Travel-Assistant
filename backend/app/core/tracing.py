import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def setup_tracing() -> None:
    """Invia a Phoenix le trace di ogni esecuzione dell'agente: chiamate al modello, tool, input e output.

    Phoenix e' un server a parte (porta 6006). Se non e' acceso l'app funziona lo stesso: le trace vanno perse.
    """
    if not settings.tracing_enabled:
        return

    # Import qui: se il tracing e' spento i pacchetti non servono
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from phoenix.otel import register

    # set_global_tracer_provider=False: senza un tracer globale FastAPI non invia le sue tracce (richieste HTTP);
    # in Phoenix restano solo quelle dell'agente e dei tool
    tracer_provider = register(
        project_name=settings.phoenix_project, endpoint=settings.phoenix_endpoint, batch=True, verbose=False,
        set_global_tracer_provider=False,
    )
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
    logger.info("Tracing attivo: progetto '%s' su %s", settings.phoenix_project, settings.phoenix_endpoint)
