from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str
    
    # Anthropic
    anthropic_api_key: str

    # Pipeline
    analysis_version: str = "v1"
    pipeline_workers: int = 5
    pipeline_batch_size: int = 10

    # Voyage AI (embeddings)
    voyage_api_key: str | None = None

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    allowed_origins: str | None = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()