"""Configurações centralizadas do Assistente Pessoal."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configurações carregadas a partir de variáveis de ambiente e arquivo .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("*", mode="before")
    @classmethod
    def _strip_env_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    # Telegram
    telegram_bot_token: str = ""
    telegram_user_id: int | None = None
    telegram_webhook_secret: str = ""
    storage_channel_id: int | None = None

    # Criptografia
    storage_encryption_key: str = ""

    # Banco de dados (SQLite local ou Neon Postgres via DATABASE_URL / POSTGRES_URL)
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'data' / 'assistant.db'}"
    postgres_url: str = ""

    # Servidor Web / PWA
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    web_access_user: str = "admin"
    web_access_token: str = ""
    web_2fa_enabled: bool = False
    public_url: str = ""

    # Sincronização com Canal
    sync_debounce_seconds: int = Field(default=60, ge=5)
    sync_enabled: bool = True

    # IA / Voz Opcional
    ai_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    whisper_model: str = "small"
    groq_api_key: str = ""
    gemini_api_key: str = ""

    @property
    def effective_database_url(self) -> str:
        env_pg = self.postgres_url.strip() or os.getenv("POSTGRES_URL", "").strip()
        # Se DATABASE_URL foi explicitamente definida (ex: Neon), prioriza; senão usa POSTGRES_URL se existir
        if "sqlite" not in self.database_url:
            return self.database_url
        if env_pg:
            return env_pg
        return self.database_url

    @property
    def is_vercel(self) -> bool:
        return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))

    @property
    def effective_public_url(self) -> str:
        if self.public_url.strip():
            return self.public_url.strip().rstrip("/")
        vercel_prod = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        if vercel_prod:
            return f"https://{vercel_prod}"
        vercel_url = os.getenv("VERCEL_URL", "").strip()
        if vercel_url:
            return f"https://{vercel_url}"
        return f"http://{self.web_host}:{self.web_port}"

    @property
    def data_dir(self) -> Path:
        path = PROJECT_ROOT / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite+aiosqlite:///"
        url = self.effective_database_url
        if url.startswith(prefix):
            raw = url[len(prefix) :]
            if raw == ":memory:":
                return None
            p = Path(raw)
            if not p.is_absolute():
                p = (PROJECT_ROOT / p).resolve()
            return p
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância singleton de Settings."""
    return Settings()

