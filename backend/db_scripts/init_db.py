"""Crea le tabelle del database SQLite a partire dai modelli.

Uso (da backend/):
    python -m db_scripts.init_db            # crea le tabelle mancanti
    python -m db_scripts.init_db --reset    # cancella tutto e ricrea (serve se lo schema e' cambiato)
"""

import sys

from app.db.session import Base, engine
from app.models import models  # noqa: F401  (registra i modelli su Base)

def init_db(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

if __name__ == "__main__":
    init_db(reset="--reset" in sys.argv)
    print(f"Database pronto: {engine.url}")
    print("Tabelle:", ", ".join(sorted(Base.metadata.tables)))
