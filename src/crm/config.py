"""Configuración desde variables de entorno (y `.env`, si existe)."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = ""
    crm_db_path: Path = Path("data/crm.db")
    crm_host: str = "127.0.0.1"
    crm_port: int = 8000
    crm_vault_path: Path | None = None
    # Solo poner a True detrás de HTTPS (despliegue en servidor).
    crm_secure_cookies: bool = False
    # Token del MCP por HTTP (/mcp). Vacío = /mcp desactivado (en local basta el MCP por stdio).
    crm_mcp_token: str = ""

    @field_validator("crm_vault_path", mode="before")
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        # `CRM_VAULT_PATH=` vacío en el .env significa "sin configurar", no "carpeta actual".
        return None if value == "" else value

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.crm_db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
