from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="verifyflow-tests-"))
os.environ["VERIFYFLOW_ENVIRONMENT"] = "test"
os.environ["VERIFYFLOW_DATABASE_URL"] = f"sqlite:///{(_TMP / 'unused.db').as_posix()}"
os.environ["VERIFYFLOW_STORAGE_DIR"] = str(_TMP / "storage")
os.environ["VERIFYFLOW_AI_PROVIDER"] = "disabled"
# Hermetic AI settings: a developer's key or egress policy must never reach tests (no test calls a real provider).
os.environ["VERIFYFLOW_AI_API_KEY"] = ""
os.environ["VERIFYFLOW_AI_DOCUMENT_EGRESS"] = "none"
os.environ["VERIFYFLOW_AI_MASK_IDENTIFIERS"] = "true"
os.environ["VERIFYFLOW_AI_MAX_RETRIES"] = "2"
os.environ["VERIFYFLOW_AI_DAILY_BUDGET_USD"] = "5"
os.environ["VERIFYFLOW_AI_RATE_LIMIT_PER_MINUTE"] = "20"
os.environ["VERIFYFLOW_AI_USER_RATE_LIMIT_PER_HOUR"] = "60"
os.environ["VERIFYFLOW_AI_BASE_URL"] = ""
os.environ["VERIFYFLOW_AI_MODEL"] = "claude-opus-5-5"
os.environ["VERIFYFLOW_AI_INPUT_USD_PER_MTOK"] = "4"
os.environ["VERIFYFLOW_AI_OUTPUT_USD_PER_MTOK"] = "20"
# Hermetic trust settings: a developer's local .env must not change test behaviour.
os.environ["VERIFYFLOW_TRUST_ROOTS_DIR"] = ""
os.environ["VERIFYFLOW_TRUST_CRL_DIR"] = ""
os.environ["VERIFYFLOW_TRUST_REVOCATION_FETCHING"] = "false"
os.environ["VERIFYFLOW_REGISTRY_CONNECTORS"] = "[]"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.roles import Role  # noqa: E402
from app.db.session import get_db, get_session_factory, make_engine  # noqa: E402
from app.extraction.ocr import UnavailableOcrEngine, get_ocr_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import user_service  # noqa: E402
from app.services.audit_service import AuditContext  # noqa: E402
from app.services.storage import LocalStorage, get_storage  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE_DB = _TMP / "template.db"
PASSWORD = "Correct-Horse-42"


# Opt-in: run the suite against PostgreSQL. Point this at a server you may create and drop databases on, e.g.
# postgresql+psycopg://postgres@127.0.0.1:5432/postgres. Each test gets its own database copied from a migrated
# template. Unset (the default), tests use SQLite files.
PG_URL = os.environ.get("VERIFYFLOW_TEST_POSTGRES_URL", "")
PG_TEMPLATE = "verifyflow_test_template"


def _migrate(url: str) -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")


def _pg_admin(statement: str) -> None:
    from sqlalchemy import create_engine, text

    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(statement))
    admin.dispose()


def _pg_release_template() -> None:
    """CREATE DATABASE ... TEMPLATE needs the template to have no other connections (e.g. Alembic's)."""
    _pg_admin(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{PG_TEMPLATE}' AND pid <> pg_backend_pid()"
    )


def _pg_url(database: str) -> str:
    return PG_URL.rsplit("/", 1)[0] + "/" + database


@pytest.fixture(scope="session", autouse=True)
def _template_db() -> Iterator[None]:
    if PG_URL:
        _pg_admin(f"DROP DATABASE IF EXISTS {PG_TEMPLATE}")
        _pg_admin(f"CREATE DATABASE {PG_TEMPLATE}")
        _migrate(_pg_url(PG_TEMPLATE))
    else:
        _migrate(f"sqlite:///{TEMPLATE_DB.as_posix()}")
    yield
    if PG_URL:
        _pg_release_template()
        _pg_admin(f"DROP DATABASE IF EXISTS {PG_TEMPLATE}")
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker]:
    if PG_URL:
        name = f"verifyflow_test_{uuid.uuid4().hex[:12]}"
        _pg_release_template()
        _pg_admin(f"CREATE DATABASE {name} TEMPLATE {PG_TEMPLATE}")
        engine = make_engine(_pg_url(name))
    else:
        db_path = tmp_path / "test.db"
        shutil.copy(TEMPLATE_DB, db_path)
        engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()
    if PG_URL:
        _pg_admin(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture
def db(session_factory: sessionmaker) -> Iterator[Session]:
    with session_factory() as s:
        yield s


BASE_URL = "https://testserver"  # https so Secure / __Host- cookies behave as in a browser


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    """Private per-test document storage."""
    return LocalStorage(root=tmp_path / "storage")


@pytest.fixture
def client_factory(session_factory: sessionmaker, storage: LocalStorage) -> Iterator:
    """Each call returns an independent client (own cookie jar), like a separate browser."""

    def _get_db() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    # Background processing jobs use the test database and test storage.
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage  # tests may replace this to simulate failures
    # Deterministic OCR: unavailable unless a test installs a fake engine.
    app.dependency_overrides[get_ocr_engine] = lambda: UnavailableOcrEngine("OCR disabled in tests")
    clients: list[TestClient] = []

    def _new() -> TestClient:
        c = TestClient(app, base_url=BASE_URL)
        clients.append(c)
        return c

    yield _new
    for c in clients:
        c.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client(client_factory) -> TestClient:
    """Anonymous client."""
    return client_factory()


@pytest.fixture
def make_user(session_factory: sessionmaker):
    def _make(
        role: Role = Role.ADMIN, email: str | None = None, password: str = PASSWORD, active: bool = True,
        institution_id: str | None = None,
    ):
        with session_factory() as s:
            user = user_service.create_user(
                s, AuditContext(request_id="test"),
                email=email or f"{role.value}@example.org", full_name=f"Test {role.value}",
                role=role, password=password, institution_id=institution_id,
            )
            user.is_active = active
            s.commit()
            return user

    return _make


@pytest.fixture
def login(client_factory):
    """Sign in on a fresh client; the CSRF header is pre-set as the SPA would send it."""

    def _login(email: str, password: str = PASSWORD) -> TestClient:
        c = client_factory()
        r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c

    return _login


@pytest.fixture
def make_institution(session_factory: sessionmaker):
    """Create an extra institution (a second tenant) and return its id."""
    from app.services import institution_service

    def _make(code: str = "COLLEGE-B", name: str = "Synthetic College B") -> str:
        with session_factory() as s:
            inst = institution_service.create(s, AuditContext(request_id="test"), name=name, code=code)
            s.commit()
            return inst.id

    return _make


@pytest.fixture
def auth_as(make_user, login):
    def _as(role: Role, email: str | None = None) -> TestClient:
        user = make_user(role, email=email)
        return login(user.email)

    return _as
