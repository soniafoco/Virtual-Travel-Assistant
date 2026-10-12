import os
import tempfile
from pathlib import Path

# Va impostato prima di importare `app`: l'engine e Chroma leggono le impostazioni all'import.
# I test usano un database e un indice vettoriale temporanei: non toccano mai
# travel.db ne' chroma_data/.
_tmp_dir = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp_dir / 'test.db').as_posix()}"
os.environ["CHROMA_PATH"] = (_tmp_dir / "chroma").as_posix()
os.environ["TRACING_ENABLED"] = "false"  # i test non inviano trace a Phoenix
os.environ["EMBEDDING_PROVIDER"] = "huggingface"  # embedding locale: i test non chiamano Gemini
os.environ["LOG_FILE"] = (_tmp_dir / "logs" / "app.log").as_posix()

import pytest  # noqa: E402

from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.models import models  # noqa: E402,F401

@pytest.fixture
def db():
    """Sessione su uno schema vuoto, ricreato per ogni test."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
