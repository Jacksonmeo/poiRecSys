"""Application settings loaded from environment variables or backend/.env.

Secrets and connection credentials never have non-empty code defaults.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    database_url: str = Field(min_length=1)
    recommendation_model_name: str = "T10e2_CausalMemoryFusion"

    llm_provider: str = "mock"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: int = Field(default=30, gt=0)

    agent_context_backend: Literal["memory", "postgres_redis"] = "postgres_redis"
    agent_context_max_tokens: int = Field(default=6000, ge=512)
    agent_context_postgres_pool_size: int = Field(default=5, gt=0)
    agent_context_cache_ttl_seconds: int = Field(default=1800, gt=0)
    agent_thread_lock_timeout_seconds: int = Field(default=120, gt=0)
    agent_thread_lock_wait_seconds: int = Field(default=5, gt=0)
    redis_url: str = ""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
