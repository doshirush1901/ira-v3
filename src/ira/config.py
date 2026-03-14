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


_COMMON = dict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", **_COMMON)

    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1"
    anthropic_model: str = "claude-sonnet-4-20250514"


class EmbeddingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOYAGE_", **_COMMON)

    api_key: SecretStr = SecretStr("")
    model: str = "voyage-3"
    rerank_model: str = "rerank-2.5"


class QdrantConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_", **_COMMON)

    url: str = "http://localhost:6333"
    api_key: SecretStr = SecretStr("")
    collection: str = "ira_knowledge_v3"
    # Optional: when set, every upsert and ensure_collection is mirrored to this
    # cluster so local and cloud stay in sync (dual-write).
    cloud_url: str = ""
    cloud_api_key: SecretStr = SecretStr("")


class Neo4jConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEO4J_", **_COMMON)

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: SecretStr = SecretStr("")
    auth: str = ""

    def resolved_auth(self) -> tuple[str, str]:
        """Resolve Neo4j credentials from explicit password or NEO4J_AUTH."""
        user = self.user.strip() or "neo4j"
        password = self.password.get_secret_value().strip()
        if password:
            return user, password

        auth = self.auth.strip()
        if "/" in auth:
            auth_user, auth_password = auth.split("/", 1)
            auth_user = auth_user.strip() or user
            auth_password = auth_password.strip()
            if auth_password:
                return auth_user, auth_password
        if "localhost" in self.uri or "127.0.0.1" in self.uri:
            # Local docker-compose default (safe dev fallback).
            return user, "ira_knowledge_graph"
        return user, ""


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_", **_COMMON)

    url: str = "postgresql+asyncpg://ira:ira@localhost:5432/ira_crm"


class MemoryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEM0_", **_COMMON)

    api_key: SecretStr = SecretStr("")


class GoogleConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOOGLE_", **_COMMON)

    credentials_path: Path = Path("credentials.json")
    token_path: Path = Path("token.json")
    oauth_client_id: str = ""
    oauth_client_secret: SecretStr = SecretStr("")
    ira_email: str = ""
    training_email: str = ""
    email_mode: EmailMode = Field(
        default=EmailMode.TRAINING,
        validation_alias="IRA_EMAIL_MODE",
    )
    email_poll_enabled: bool = Field(
        default=False,
        validation_alias="IRA_EMAIL_POLL",
    )


class ExternalAPIsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEWSDATA_", **_COMMON)

    api_key: SecretStr = SecretStr("")


class SearchConfig(BaseSettings):
    model_config = SettingsConfigDict(**_COMMON)

    tavily_api_key: SecretStr = SecretStr("")
    searchapi_api_key: SecretStr = SecretStr("")
    serper_api_key: SecretStr = SecretStr("")


class PdfCoConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PDFCO_", **_COMMON)

    api_key: SecretStr = SecretStr("")


class DocumentAIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCUMENT_AI_", **_COMMON)

    project_id: str = Field(default="", validation_alias="GOOGLE_CLOUD_PROJECT_ID")
    location: str = "us"
    processor_id: str = ""
    invoice_processor_id: str = ""
    form_processor_id: str = ""


class LangfuseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_", **_COMMON)

    public_key: str = ""
    secret_key: SecretStr = SecretStr("")
    base_url: str = "https://cloud.langfuse.com"


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", **_COMMON)

    url: str = ""


class HeliconeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HELICONE_", **_COMMON)

    api_key: SecretStr = SecretStr("")


class FirecrawlConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRECRAWL_", **_COMMON)

    api_key: SecretStr = SecretStr("")


class UnstructuredConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNSTRUCTURED_", **_COMMON)

    api_key: SecretStr = SecretStr("")
    api_url: str = "https://api.unstructuredapp.io/general/v0/general"


class SentryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTRY_", **_COMMON)

    dsn: str = ""
    traces_sample_rate: float = 0.1


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(**_COMMON)

    log_level: str = "INFO"
    log_format: str = "text"
    environment: str = "development"
    api_secret_key: SecretStr = SecretStr("")
    cors_origins: str = "http://localhost:3000"
    react_max_iterations: int = 8
    agent_timeout: int = 90
    mem0_timeout: float = 15.0
    neo4j_max_pool_size: int = 50

    max_delegation_depth: int = 5

    faithfulness_threshold: float = 0.6
    faithfulness_hard_threshold: float = 0.3
    confidence_floor: float = 0.3
    guardrails_fail_closed: bool = True
    mnemon_semantic_check: bool = False
    legacy_quarantine_strict: bool = False


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
    pdfco: PdfCoConfig = PdfCoConfig()
    document_ai: DocumentAIConfig = DocumentAIConfig()
    redis: RedisConfig = RedisConfig()
    google: GoogleConfig = GoogleConfig()
    external_apis: ExternalAPIsConfig = ExternalAPIsConfig()
    search: SearchConfig = SearchConfig()
    langfuse: LangfuseConfig = LangfuseConfig()
    helicone: HeliconeConfig = HeliconeConfig()
    firecrawl: FirecrawlConfig = FirecrawlConfig()
    unstructured: UnstructuredConfig = UnstructuredConfig()
    sentry: SentryConfig = SentryConfig()
    app: AppConfig = AppConfig()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
