from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt non usa piu' di 72 byte

    @field_validator("name")
    @classmethod
    def controlla_nome(cls, valore):
        if valore.strip() == "":  # solo spazi non e' un nome
            raise ValueError("Il nome non puo' essere vuoto.")
        return valore.strip()

    @field_validator("password")
    @classmethod
    def controlla_password(cls, valore):
        if valore.strip() == "":
            raise ValueError("La password non puo' contenere solo spazi.")
        # il limite di bcrypt e' in byte, non in caratteri: una lettera accentata ne occupa 2
        if len(valore.encode()) > 72:
            raise ValueError("La password e' troppo lunga: massimo 72 byte (le lettere accentate ne occupano di piu').")
        return valore

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
