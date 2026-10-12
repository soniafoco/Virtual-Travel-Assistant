from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    """Hash bcrypt con salt casuale: la password in chiaro non viene mai salvata."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())

def create_access_token(user_id: int) -> str:
    """Un JWT firmato con l'id utente (`sub`) e la scadenza (`exp`)."""
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.secret_key, algorithm=ALGORITHM)

def decode_access_token(token: str) -> int:
    """L'id utente nel token. Con un token scaduto o manomesso alza jwt.InvalidTokenError."""
    # `algorithms` va sempre indicato: cosi' un token non puo' scegliere da solo come farsi verificare
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    return int(payload["sub"])
