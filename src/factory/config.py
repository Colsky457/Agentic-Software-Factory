"""Agentic Software Factory configuration.

All configuration is managed via Pydantic settings, which read from environment
variables and a `.env` file. Defaults are tuned for local development; override
via environment for production.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Factory ----
    factory_name: str = Field(default="agentic-software-factory", description="Factory identifier")
    base_dir: str = Field(default=".factory", description="Working directory for factory artifacts")
    worktrees_dir: str = Field(default=".factory/worktrees", description="Git worktree sandbox root")
    max_retries: int = Field(default=3, description="Max agent retry attempts before HITL escalation")

    # ---- LLM ----
    llm_provider: str = Field(default="openai", description="LLM provider: openai, anthropic, ollama, liteLLM")
    llm_model: str = Field(default="gpt-4o", description="Default LLM model")
    llm_api_key: str | None = Field(default=None, description="LLM API key")
    llm_base_url: str | None = Field(default=None, description="Custom LLM base URL (Ollama/LiteLLM)")
    llm_temperature: float = Field(default=0.2, description="LLM sampling temperature")
    llm_max_tokens: int = Field(default=4096, description="Max completion tokens")

    # ---- Observability ----
    log_level: str = Field(default="INFO", description="Structured log level")
    enable_tracing: bool = Field(default=True, description="Enable OpenTelemetry tracing")
    otlp_endpoint: str | None = Field(default=None, description="OTLP trace endpoint")
    dashboard_host: str = Field(default="0.0.0.0", description="Dashboard bind host")
    dashboard_port: int = Field(default=8000, description="Dashboard bind port")

    # ---- Git / GitHub ----
    github_token: str | None = Field(default=None, description="GitHub API token")
    github_owner: str | None = Field(default=None, description="GitHub owner/org")
    default_branch: str = Field(default="main", description="Default branch")

    # ---- HITL ----
    hitl_auto_approve: bool = Field(default=False, description="Auto-approve all HITL gates (dev only)")
    hitl_timeout_seconds: int = Field(default=3600, description="HITL gate timeout")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


settings = Settings()

__all__ = ["Settings", "settings"]
