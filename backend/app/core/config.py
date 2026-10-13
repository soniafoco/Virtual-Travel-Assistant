from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

Provider = Literal["gemini", "huggingface"]  # embedding
LlmProvider = Literal["gemini", "huggingface", "groq"]  # chat

BACKEND_DIR = Path(__file__).resolve().parents[2]
# gli unici campi che si leggono da .env: i segreti e la configurazione dell'ambiente (dove stanno dati e log)
ENV_FIELDS = {"gemini_api_key", "hf_token", "groq_api_key", "secret_key", "database_url", "chroma_path", "log_file", "log_level"}

class Airport(BaseModel):
    code: str  # IATA
    name: str
    city: str

class SecretsDotEnv(DotEnvSettingsSource):
    """Da .env passano solo i campi di ENV_FIELDS: provider, modelli e il resto stanno in config.yaml."""

    def __call__(self):
        return {key: value for key, value in super().__call__().items() if key in ENV_FIELDS}

class Settings(BaseSettings):
    """Valori da config.yaml (provider, modelli, parametri) e da .env (segreti, database, percorsi, log).

    Precedenza: variabili d'ambiente del sistema > .env (solo ENV_FIELDS) > config.yaml > default qui sotto.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", yaml_file=BACKEND_DIR / "config.yaml", extra="ignore",
    )

    # chat e embedding
    llm_provider: LlmProvider = "gemini"
    embedding_provider: Provider = "gemini"
    llm_temperature: float | None = None  # None = default del modello
    gemini_model: str = "gemini-3.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_task_type: str = "SEMANTIC_SIMILARITY"
    hf_model: str = "HuggingFaceTB/SmolLM-135M"
    hf_max_new_tokens: int = 1024
    groq_model: str = "openai/gpt-oss-120b"
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # RAG e ricerca attivita'
    chroma_collection: str = "activities"
    min_affinity: dict[Provider, float] = {"gemini": 0.82, "huggingface": 0.4}
    max_activities: int = 10
    category_queries: dict[str, str] = {}

    # chat
    chat_history_messages: int = 20

    # tracing con Phoenix (server a parte, vedi config.yaml)
    tracing_enabled: bool = False
    phoenix_endpoint: str = "http://localhost:6006/v1/traces"
    phoenix_project: str = "virtual-travel-assistant"

    # planner e requisiti
    planner_alternatives: int = 3
    home_country: str = "Italia"
    max_travelers: int = 8
    default_nights: int = 7
    min_nights: int = 2
    max_nights: int = 14
    airports: list[Airport] = []

    # dati e server
    database_url: str = "sqlite:///./travel.db"
    chroma_path: str = "./chroma_data"
    reseed: bool = False
    access_token_minutes: int = 60 * 24
    cors_origins: list[str] = ["http://localhost:5173"]
    log_file: str = "./logs/app.log"
    log_level: str = "INFO"
    log_format: str = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    log_max_bytes: int = 1_000_000
    log_body_chars: int = 1000
    log_backup_count: int = 3

    # segreti (.env)
    gemini_api_key: str = ""
    hf_token: str = ""
    groq_api_key: str = ""
    secret_key: str = "change-me"

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            SecretsDotEnv(settings_cls),
            YamlConfigSettingsSource(settings_cls),
        )

settings = Settings()
