from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5433, ge=1, le=65535)
    postgres_db: str = "knowledge_agent"
    postgres_user: str = "knowledge_agent"
    postgres_password: SecretStr

    embedding_model: str = "embeddinggemma"
    embedding_dimension: int = Field(default=768, ge=1)
    generation_model: str = "qwen3:4b"

    chunk_size: int = Field(default=500, ge=1)
    chunk_overlap: int = Field(default=50, ge=0)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1)

    postgres_pool_min_size: int = Field(default=1, ge=1)
    postgres_pool_max_size: int = Field(default=10, ge=1)
    postgres_connect_timeout_seconds: int = Field(default=5, ge=1)
    postgres_statement_timeout_ms: int = Field(default=30_000, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
