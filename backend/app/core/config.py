"""Application settings loaded from environment variables / .env.

No secrets are hardcoded. Authentication uses random server-side session tokens
(stored only as SHA-256 hashes), so no signing secret is needed. Invalid values
stop startup with a readable ConfigError.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env", env_prefix="VERIFYFLOW_", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "VerifyFlow AI"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    # Interactive OpenAPI docs at /api/docs. Default: on, except in production.
    expose_api_docs: bool | None = None

    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'var' / 'verifyflow.db').as_posix()}"
    # Uploaded files live here: outside any public web root, served only via authorized endpoints.
    storage_dir: Path = BACKEND_ROOT / "var" / "storage"
    # Optional institution-portal transport. Disabled unless both values are configured.
    portal_shared_secret: SecretStr | None = None
    portal_owner_email: str | None = None
    portal_reviewer_email: str | None = None
    portal_auto_assign: bool = True
    # Explicit opt-in for a public evaluator walkthrough. Never point this at regular account credentials.
    evaluator_autofill: bool = False
    evaluator_accounts_file: Path = BACKEND_ROOT / "var" / "demo-accounts.txt"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # "text" for humans during development, "json" for log shippers in production.
    log_format: Literal["text", "json"] = "text"

    # Server-side sessions in HttpOnly cookies. A session ends after this much inactivity...
    session_idle_minutes: int = Field(default=30, ge=1, le=24 * 60)
    # ...and unconditionally after this long, however active it is.
    session_absolute_hours: int = Field(default=12, ge=1, le=7 * 24)
    # Secure cookies are sent only over HTTPS (browsers also accept them on http://localhost).
    # Set false only for plain-HTTP testing on another hostname; refused in production.
    cookie_secure: bool = True

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=512 * 1024 * 1024)
    # Structural limits checked on every upload.
    max_pdf_pages: int = Field(default=500, ge=1, le=10_000)
    max_image_pixels: int = Field(default=60_000_000, ge=10_000, le=500_000_000)
    max_documents_per_application: int = Field(default=200, ge=1, le=10_000)
    # A processing job still "running" after this long is treated as interrupted and may be retried.
    processing_stale_minutes: int = Field(default=15, ge=1, le=24 * 60)
    # inline: the API process runs jobs as background tasks (local development). worker: the API only queues jobs and
    # `python -m app.cli worker` runs them from the database, so jobs survive API restarts and OCR load is isolated.
    processing_mode: Literal["inline", "worker"] = "inline"
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=300)
    # The worker re-queues an interrupted job until this many attempts, then leaves it failed for a person to retry.
    processing_max_attempts: int = Field(default=3, ge=1, le=20)

    # Login throttling over a sliding window. Counted per submitted email (whether or not the
    # account exists, so throttling reveals nothing) and per client IP.
    login_window_minutes: int = Field(default=15, ge=1, le=24 * 60)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_ip_max_failures: int = Field(default=30, ge=1, le=10_000)

    # ---- AI assistance (Phase 9). Advisory only: compliance evaluation, trust checks and review decisions never
    # depend on it. "disabled" = no-AI mode; "anthropic" = Claude via the official Anthropic SDK.
    ai_provider: str = Field(default="disabled", pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    # Read only from the backend environment; never returned by the API, logged or stored.
    ai_api_key: SecretStr | None = None
    # Provider model id; Groq ids carry an owner prefix such as "openai/gpt-oss-120b".
    ai_model: str = Field(default="claude-opus-5-5", pattern=r"^[a-z0-9][a-z0-9./\-]{2,79}$")
    ai_base_url: str | None = None  # optional gateway/proxy in front of the provider API
    ai_effort: Literal["low", "medium", "high"] = "medium"
    # Retry a declined request server-side on the provider's recommended fallback model.
    ai_refusal_fallback: bool = True
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    # Retries after the first attempt, for timeouts, provider rate limits and 5xx only.
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    ai_max_output_tokens: int = Field(default=2048, ge=256, le=16_000)
    # Hard cap on characters sent per request; longer context is cut at a page boundary and the cut is recorded.
    ai_max_input_chars: int = Field(default=24_000, ge=1_000, le=400_000)
    ai_rate_limit_per_minute: int = Field(default=20, ge=1, le=10_000)  # whole process
    ai_user_rate_limit_per_hour: int = Field(default=60, ge=1, le=10_000)  # per user
    # Spend ceiling per UTC day across all users, estimated before each call from the configured prices.
    ai_daily_budget_usd: float = Field(default=5.0, ge=0, le=100_000)
    ai_input_usd_per_mtok: float = Field(default=4.0, ge=0, le=1_000)
    ai_output_usd_per_mtok: float = Field(default=20.0, ge=0, le=1_000)
    # What may leave this environment: "none" (rule and finding metadata only, no document content),
    # "extracted_values" (+ extracted and corrected field values), "page_text" (+ page text, needed for
    # classification and field suggestions).
    ai_document_egress: Literal["none", "extracted_values", "page_text"] = "none"
    # Mask identifier-type values (IDs, account numbers) to their last 4 characters before they leave.
    ai_mask_identifiers: bool = True

    # Field definitions JSON for extraction (default: app/extraction/field_definitions.json).
    field_definitions_path: str | None = None
    # Cross-document comparison groups (default: app/evidence/comparison_config.json).
    comparison_config_path: str | None = None
    # Upper bound on OCR'd pages per document (OCR is slow); further pages are recorded as skipped.
    ocr_max_pages: int = Field(default=50, ge=1, le=2000)

    # Optional explicit path to the Tesseract binary for OCR of scanned documents.
    tesseract_cmd: str | None = None

    # ---- Trust and authentication (Phase 8). Nothing is trusted by default.
    # Directory of PEM/DER certificates used as trust anchors for PDF signatures (never the OS TLS trust list).
    trust_roots_dir: Path | None = None
    # Directory of offline CRLs (PEM/DER) for revocation checks without network access.
    trust_crl_dir: Path | None = None
    # Online OCSP/CRL fetching from URLs inside certificates. Off by default: enable only with controlled egress
    # (an allowlisting proxy), because those URLs come from uploaded documents.
    trust_revocation_fetching: bool = False
    # Approved issuer/registry integrations, by key: "synthetic" (dev/test only), "http_json".
    registry_connectors: list[str] = []
    registry_synthetic_path: Path | None = None
    registry_http_url: str | None = None
    registry_http_name: str = "Configured issuer registry"
    registry_http_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("trust_roots_dir", "trust_crl_dir", "registry_synthetic_path", mode="before")
    @classmethod
    def _empty_path(cls, v: object) -> object:
        return None if v == "" else v

    @field_validator("registry_connectors")
    @classmethod
    def _connectors(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - {"synthetic", "http_json"})
        if unknown:
            raise ValueError(f"unknown registry connector(s): {', '.join(unknown)}")
        return v

    @field_validator("registry_http_url")
    @classmethod
    def _registry_url(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~/%-]*)?", v):
            raise ValueError("must be an http(s) URL without query string or credentials")
        return v or None

    @field_validator("ai_api_key", mode="before")
    @classmethod
    def _empty_key(cls, v: object) -> object:
        return None if v == "" else v

    @field_validator("ai_base_url")
    @classmethod
    def _ai_base_url(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~/%-]*)?", v):
            raise ValueError("must be an http(s) URL without query string or credentials")
        return v or None

    @field_validator("database_url")
    @classmethod
    def _db_url(cls, v: str) -> str:
        if not v.startswith(("sqlite://", "postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
            raise ValueError("must be a sqlite:// or postgresql:// SQLAlchemy URL")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _cors(cls, v: list[str]) -> list[str]:
        for origin in v:
            if origin == "*":
                raise ValueError("wildcard '*' is not allowed; list explicit origins")
            if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?", origin):
                raise ValueError(f"invalid origin {origin!r}; expected scheme://host[:port] without a path")
        return v

    @field_validator("tesseract_cmd")
    @classmethod
    def _tesseract(cls, v: str | None) -> str | None:
        if v and not Path(v).is_file():
            raise ValueError(f"file not found: {v}")
        return v or None

    @model_validator(mode="after")
    def _check_storage(self) -> Settings:
        storage = self.storage_dir.resolve()
        frontend = (BACKEND_ROOT.parent / "frontend").resolve()
        if storage == frontend or frontend in storage.parents:
            raise ValueError("VERIFYFLOW_STORAGE_DIR must not be inside the frontend (public) tree")
        return self

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.environment == "production":
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is for local development only; use PostgreSQL in production")
            if any(o.startswith("http://") for o in self.cors_origins):
                raise ValueError("Production CORS origins must use https://")
            if not self.cookie_secure:
                raise ValueError("VERIFYFLOW_COOKIE_SECURE must be true in production")
            if "synthetic" in self.registry_connectors:
                raise ValueError("The synthetic registry connector is for development and tests only")
            if self.registry_http_url and not self.registry_http_url.startswith("https://"):
                raise ValueError("VERIFYFLOW_REGISTRY_HTTP_URL must use https:// in production")
            if self.ai_base_url and not self.ai_base_url.startswith("https://"):
                raise ValueError("VERIFYFLOW_AI_BASE_URL must use https:// in production")
        return self

    @property
    def api_docs_enabled(self) -> bool:
        return self.expose_api_docs if self.expose_api_docs is not None else self.environment != "production"

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix makes browsers reject the cookie unless Secure, Path=/ and host-only.
        return "__Host-vf_session" if self.cookie_secure else "vf_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-vf_csrf" if self.cookie_secure else "vf_csrf"


class ConfigError(RuntimeError):
    """Raised at startup when environment configuration is invalid."""


def _describe(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "settings"
        env = f"VERIFYFLOW_{field.upper()}" if err["loc"] else "configuration"
        lines.append(f"  - {env}: {err['msg'].removeprefix('Value error, ')}")
    return "Invalid VerifyFlow configuration:\n" + "\n".join(lines)


def load_settings(**overrides: object) -> Settings:
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
