"""Phase 1 foundation: configuration validation, log redaction, request IDs, HTTPX async client."""

from __future__ import annotations

import io
import json
import logging

import httpx
import pytest

from app.core.config import ConfigError, load_settings
from app.core.logging import REDACTED, JsonFormatter, RedactionFilter, redact_text, redact_value, request_id_var
from app.main import app

API = "/api/v1"
# Otherwise-valid production settings, so each case isolates a single rule.
PROD = {
    "environment": "production",
    "database_url": "postgresql+psycopg://vf@db.example.com/verifyflow",
    "cors_origins": ["https://app.example.com"],
}


# ---------------------------------------------------------------- configuration


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"database_url": "mysql://u:p@h/db"}, "VERIFYFLOW_DATABASE_URL"),
        ({"cors_origins": ["*"]}, "wildcard"),
        ({"cors_origins": ["http://ok.example/path"]}, "without a path"),
        ({"log_level": "LOUD"}, "VERIFYFLOW_LOG_LEVEL"),
        ({"cookie_secure": "maybe"}, "VERIFYFLOW_COOKIE_SECURE"),
        ({"ai_provider": "Bad Provider!"}, "VERIFYFLOW_AI_PROVIDER"),
        ({"session_idle_minutes": 0}, "VERIFYFLOW_SESSION_IDLE_MINUTES"),
        ({"login_max_failures": 0}, "VERIFYFLOW_LOGIN_MAX_FAILURES"),
        ({"tesseract_cmd": "C:/definitely/missing/tesseract.exe"}, "file not found"),
        ({**PROD, "cookie_secure": False}, "COOKIE_SECURE must be true"),
        ({**PROD, "cors_origins": ["http://app.example.com"]}, "https://"),
        (
            {**PROD, "database_url": "sqlite:///p.db"},
            "PostgreSQL in production",
        ),
    ],
)
def test_invalid_configuration_is_rejected_with_readable_message(overrides, fragment):
    with pytest.raises(ConfigError) as exc:
        load_settings(**overrides)
    assert "Invalid VerifyFlow configuration" in str(exc.value)
    assert fragment in str(exc.value)


def test_storage_inside_frontend_rejected(tmp_path):
    from app.core.config import BACKEND_ROOT

    with pytest.raises(ConfigError, match="frontend"):
        load_settings(storage_dir=BACKEND_ROOT.parent / "frontend" / "public" / "uploads")


def test_valid_production_configuration_loads():
    assert load_settings(**PROD).environment == "production"


def test_api_docs_are_off_in_production_unless_enabled():
    assert load_settings(**PROD).api_docs_enabled is False
    assert load_settings(**PROD, expose_api_docs=True).api_docs_enabled is True
    assert load_settings().api_docs_enabled is True


def test_the_production_env_template_loads_once_placeholders_are_filled(tmp_path, monkeypatch):
    """deploy/.env.production.example must stay valid: every variable known, and accepted in production."""
    from pathlib import Path

    from app.core.config import Settings

    template = Path(__file__).resolve().parents[2] / "deploy" / ".env.production.example"
    env = {}
    for line in template.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    known = {f"VERIFYFLOW_{name.upper()}" for name in Settings.model_fields}
    compose_only = {"POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "VERIFYFLOW_DOMAIN"}
    assert set(env) <= known | compose_only, set(env) - known - compose_only
    assert "REPLACE_ME" in env["VERIFYFLOW_DATABASE_URL"] and env["POSTGRES_PASSWORD"] == "REPLACE_ME"
    for k in list(__import__("os").environ):
        if k.startswith("VERIFYFLOW_"):
            monkeypatch.delenv(k)
    for k, v in env.items():
        if k.startswith("VERIFYFLOW_") and k not in compose_only:
            monkeypatch.setenv(k, v.replace("REPLACE_ME", "placeholder"))
    monkeypatch.setenv("VERIFYFLOW_STORAGE_DIR", str(tmp_path))  # the container path doesn't exist here
    monkeypatch.delenv("VERIFYFLOW_TRUST_ROOTS_DIR", raising=False)
    settings = Settings(_env_file=None)
    assert settings.environment == "production" and settings.processing_mode == "worker"
    assert settings.cookie_secure is True and settings.api_docs_enabled is False
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_cookie_names_use_host_prefix_only_when_secure():
    assert load_settings(cookie_secure=True).session_cookie_name == "__Host-vf_session"
    assert load_settings(cookie_secure=False).session_cookie_name == "vf_session"


# ---------------------------------------------------------------- redaction


def test_redact_text_patterns():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.c2lnbmF0dXJlLXZhbHVl"
    raw = (
        f'Authorization: Bearer abc.def.ghi {{"password": "hunter2", "email": "a@b.co"}} '
        f"url?token=xyz123&page=2 jwt={jwt}"
    )
    out = redact_text(raw)
    for secret in ("abc.def.ghi", "hunter2", "xyz123", jwt):
        assert secret not in out
    assert "a@b.co" in out and "page=2" in out


def test_redact_value_by_key():
    data = {"email": "a@b.co", "new_password": "x", "nested": {"api_key": "k", "items": [{"refresh_token": "t"}]}}
    out = redact_value(data)
    assert out["email"] == "a@b.co"
    assert out["new_password"] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["items"][0]["refresh_token"] == REDACTED


def test_log_records_are_redacted_and_carry_request_id():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("verifyflow.test.redaction")
    logger.addHandler(handler)
    logger.propagate = False
    token = request_id_var.set("req-12345678")
    try:
        logger.warning("login body %s", {"email": "a@b.co", "password": "hunter2"})
        logger.warning("header was Bearer sekret-token-value")
    finally:
        request_id_var.reset(token)
        logger.removeHandler(handler)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert all(line["request_id"] == "req-12345678" for line in lines)
    text = stream.getvalue()
    assert "hunter2" not in text and "sekret-token-value" not in text
    assert "a@b.co" in text


def test_failed_login_password_never_logged(client, make_user, caplog):
    make_user()
    caplog.set_level(logging.DEBUG)
    client.post(f"{API}/auth/login", json={"email": "admin@example.org", "password": "Wr0ng-Secret-Value!"})
    assert "Wr0ng-Secret-Value!" not in caplog.text


# ---------------------------------------------------------------- request IDs and HTTPX


def test_request_id_echoed_when_valid_and_replaced_when_not(client):
    good = client.get(f"{API}/health", headers={"X-Request-ID": "client-req-0001"})
    assert good.headers["X-Request-ID"] == "client-req-0001"
    bad = client.get(f"{API}/health", headers={"X-Request-ID": "bad id with spaces\n"})
    assert bad.headers["X-Request-ID"] != "bad id with spaces\n"
    assert len(bad.headers["X-Request-ID"]) == 32


def test_error_responses_use_envelope_and_keep_request_id(client):
    r = client.post(f"{API}/auth/login", json={"email": "x"}, headers={"X-Request-ID": "trace-abcdef12"})
    assert r.status_code == 422
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert r.headers["X-Request-ID"] == "trace-abcdef12"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_health_via_httpx_async_client(session_factory):
    from app.db.session import get_db

    def _get_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get(f"{API}/health")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok", "version": app.version}
