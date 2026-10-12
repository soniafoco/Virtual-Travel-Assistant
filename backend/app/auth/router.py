import logging
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.schemas import RegisterIn, Token, UserOut
from app.auth.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Legge l'header "Authorization: Bearer <token>"; tokenUrl dice a Swagger dove fare il login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

DbSession = Annotated[Session, Depends(get_db)]

def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})

def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DbSession) -> User:
    """L'utente del token. Le altre route lo chiedono con `user: CurrentUser`."""
    try:
        user_id = decode_access_token(token)
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise unauthorized("Token non valido o scaduto.")
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized("Utente non trovato.")
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: DbSession):
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Esiste gia' un account con questa email.")
    user = User(email=email, name=data.name, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # due registrazioni quasi insieme con la stessa email: vince la prima
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Esiste gia' un account con questa email.")
    db.refresh(user)
    logger.info("Registrazione: nuovo utente %s", user.id)
    return user

@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    """Login standard OAuth2: modulo (non JSON) con `username` (l'email) e `password`."""
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not verify_password(form.password, user.password_hash):
        logger.warning("Login fallito per %s", form.username)
        raise unauthorized("Email o password non corretti.")  # stesso messaggio nei due casi: non rivela quali email esistono
    logger.info("Login riuscito: utente %s", user.id)
    return Token(access_token=create_access_token(user.id))

@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
