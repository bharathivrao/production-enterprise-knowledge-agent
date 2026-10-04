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
    evaluation_model: str = "gemma4:e4b"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_candidate_count: int = Field(default=10, ge=1, le=100)
    reranker_batch_size: int = Field(default=16, ge=1, le=128)
    reranker_max_length: int = Field(default=512, ge=128)
    reranker_min_score: float = Field(default=0.0, ge=0, le=1)
    vector_max_distance: float | None = Field(default=None, ge=0, le=2)
    max_context_tokens: int = Field(default=3500, ge=256)

    chunk_size: int = Field(default=400, ge=1)
    chunk_overlap: int = Field(default=50, ge=0)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1)

    postgres_pool_min_size: int = Field(default=1, ge=1)
    postgres_pool_max_size: int = Field(default=10, ge=1)
    postgres_connect_timeout_seconds: int = Field(default=5, ge=1)
    postgres_statement_timeout_ms: int = Field(default=30_000, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
