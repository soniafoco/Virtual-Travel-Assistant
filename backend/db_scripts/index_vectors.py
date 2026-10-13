"""Indicizza le attivita' di SQLite nel database vettoriale (ChromaDB).

Uso (da backend/, dopo il seed):
    python -m db_scripts.index_vectors            # allinea l'indice (idempotente)
    python -m db_scripts.index_vectors --reset    # cancella e ricrea la collezione
"""

import sys

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.rag import index_activities, reset_collection

if __name__ == "__main__":
    collection = reset_collection() if "--reset" in sys.argv else None
    with SessionLocal() as session:
        total = index_activities(session, collection)
    print(f"Indicizzate {total} attivita' nella collezione '{settings.chroma_collection}'")
