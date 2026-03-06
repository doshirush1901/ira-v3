from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmailMode(str, Enum):
    """Operating mode for the EmailProcessor."""

    TRAINING = "TRAINING"
    OPERATIONAL = "OPERATIONAL"


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1"
    anthropic_model: str = "claude-sonnet-4-20250514"


class EmbeddingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOYAGE_")

    api_key: SecretStr = SecretStr("")
    model: str = "voyage-3"


class QdrantConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_")

    url: str = "http://localhost:6333"
    collection: str = "ira_knowledge_v3"


class Neo4jConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEO4J_")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: SecretStr = SecretStr("")


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    url: str = "postgresql+asyncpg://ira:ira@localhost:5432/ira_crm"


class MemoryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEM0_")

    api_key: SecretStr = SecretStr("")


class TelegramConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr = SecretStr("")
    admin_chat_id: str = ""


class GoogleConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOOGLE_")

    credentials_path: Path = Path("credentials.json")
    token_path: Path = Path("token.json")
    ira_email: str = "ira@machinecraft.org"
    training_email: str = "rushabh@machinecraft.org"
    email_mode: EmailMode = Field(
        default=EmailMode.TRAINING,
        validation_alias="IRA_EMAIL_MODE",
    )


class ExternalAPIsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEWSDATA_")

    api_key: SecretStr = SecretStr("")


class AppConfig(BaseSettings):
    log_level: str = "INFO"
    environment: str = "development"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMConfig = LLMConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    qdrant: QdrantConfig = QdrantConfig()
    neo4j: Neo4jConfig = Neo4jConfig()
    database: DatabaseConfig = DatabaseConfig()
    memory: MemoryConfig = MemoryConfig()
    telegram: TelegramConfig = TelegramConfig()
    google: GoogleConfig = GoogleConfig()
    external_apis: ExternalAPIsConfig = ExternalAPIsConfig()
    app: AppConfig = AppConfig()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
