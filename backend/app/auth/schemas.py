from pydantic import BaseModel, ConfigDict, EmailStr, Field

class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt non usa piu' di 72 byte

class UserOut(BaseModel):
    """Cio' che l'API dice di un utente: mai password_hash."""

    model_config = ConfigDict(from_attributes=True)  # si puo' costruire da un oggetto SQLAlchemy User

    id: int
    name: str
    email: EmailStr

class Token(BaseModel):
    """La risposta standard OAuth2 del login."""

    access_token: str
    token_type: str = "bearer"
