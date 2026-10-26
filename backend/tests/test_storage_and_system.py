from __future__ import annotations

import io

import pytest

from app.core.errors import DomainError
from app.core.roles import Role
from app.integrations.ai.base import AIProviderUnavailable, StructuredRequest
from app.integrations.ai.disabled import DisabledProvider
from app.services.storage import (
    FileTooLarge,
    LocalStorage,
    UnsupportedFileType,
    sanitize_display_name,
)

API = "/api/v1"
PDF = b"%PDF-1.7\n%test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_storage_detects_type_by_content_and_hashes(tmp_path):
    store = LocalStorage(root=tmp_path, max_bytes=10_000)
    obj = store.save(io.BytesIO(PDF))
    assert obj.detected_mime == "application/pdf"
    assert obj.size_bytes == len(PDF)
    assert store.verify(obj.storage_key, obj.sha256)
    assert store.path(obj.storage_key).is_relative_to(tmp_path.resolve())
    assert store.save(io.BytesIO(PNG)).detected_mime == "image/png"


def test_storage_rejects_disguised_and_oversized_and_empty(tmp_path):
    store = LocalStorage(root=tmp_path, max_bytes=100)
    with pytest.raises(UnsupportedFileType):
        store.save(io.BytesIO(b"<script>alert(1)</script> pretending to be a pdf"))
    with pytest.raises(FileTooLarge):
        store.save(io.BytesIO(PDF + b"x" * 200))
    with pytest.raises(DomainError):
        store.save(io.BytesIO(b""))
    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == []


@pytest.mark.parametrize("key", ["../../etc/passwd", "a" * 48 + "/../x", "ZZ" * 24, ""])
def test_storage_rejects_path_traversal_keys(tmp_path, key):
    with pytest.raises(DomainError):
        LocalStorage(root=tmp_path).path(key)


def test_sanitize_display_name():
    assert sanitize_display_name("..\\..\\windows\\evil<>.pdf") == "evil.pdf"
    assert sanitize_display_name("") == "unnamed"
    assert sanitize_display_name("a/b/c.pdf") == "c.pdf"


def test_disabled_ai_never_fabricates():
    p = DisabledProvider()
    assert p.status().enabled is False
    with pytest.raises(AIProviderUnavailable):
        p.generate(StructuredRequest(task="explanation", system="", user_content="Is this authentic?",
                                     json_schema={}, max_output_tokens=256))
    with pytest.raises(AIProviderUnavailable):
        p.ping()


def test_health_is_public(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Request-ID"]


def test_readiness_checks_database_migrations_storage_and_backlog(client, session_factory, storage):
    from sqlalchemy import text

    from app.main import app as fastapi_app
    from app.services.storage import get_storage

    r = client.get(f"{API}/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["database"], body["migrations"], body["storage"]) == ("ok", "ok", "ok", "ok")
    assert body["processing"] == {"mode": "inline", "queued": 0, "oldest_queued_seconds": None, "stale_running": 0}
    assert not [p for p in storage.root.iterdir() if p.name.startswith(".probe-")]  # the probe cleans up

    # A database that is behind the code's migrations is not ready.
    with session_factory() as s:
        head = s.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        s.execute(text("UPDATE alembic_version SET version_num = '0010_ai_interactions'"))
        s.commit()
    r = client.get(f"{API}/health/ready")
    assert r.status_code == 503 and r.json()["migrations"] == "behind"
    with session_factory() as s:
        s.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": head})
        s.commit()

    # Unwritable private storage is not ready either.
    class Broken(type(storage)):
        def check_writable(self) -> None:
            raise OSError("read-only file system")

    fastapi_app.dependency_overrides[get_storage] = lambda: Broken(root=storage.root)
    r = client.get(f"{API}/health/ready")
    assert r.status_code == 503 and r.json()["storage"] == "error" and r.json()["status"] == "degraded"
    assert "read-only" not in r.text  # no internals in the public response


def test_capabilities_report_honestly(auth_as):
    r = auth_as(Role.REVIEWER).get(f"{API}/system/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_enabled"] is False
    caps = {c["key"]: c for c in body["capabilities"]}
    assert caps["pdf_text"]["available"] is True
    assert caps["digital_signature_validation"]["available"] is False  # no trust anchors in the test settings
    assert "No trust anchors configured" in caps["digital_signature_validation"]["detail"]
    assert "ocr" in caps


def test_error_envelope_on_404(client):
    r = client.get(f"{API}/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
