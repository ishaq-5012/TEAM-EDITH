from __future__ import annotations

from pydantic import SecretStr
import hashlib
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.roles import Role
from app.models import Application, PortalDocument, PortalSubmission
from app.models.evidence import EvidenceAnalysis, EvidenceFinding
from tests import factories


def _payload(version=1):
    return {
        "portal_application_id": "portal-app-1", "submission_version": version,
        "reference": "EDU-2026-TEST", "category_id": "new-institution",
        "category_name": "New Institution", "institution": {"id": "college-1", "name": "Example College"},
        "form": {"programme": "Engineering"}, "submitted_at": "2026-10-25T00:00:00+00:00",
        "documents": [],
    }


def test_authenticated_idempotent_submission(client, make_user, session_factory):
    user = make_user(Role.REVIEWER, email="portal-service@example.org")
    settings = get_settings()
    previous = (settings.portal_shared_secret, settings.portal_owner_email)
    settings.portal_shared_secret = SecretStr("test-secret-value")
    settings.portal_owner_email = user.email
    path = "/api/v1/portal-intake/submissions"
    try:
        assert client.post(path, json=_payload()).status_code == 401
        headers = {"X-Portal-Secret": "test-secret-value"}
        first = client.post(path, json=_payload(), headers=headers)
        assert first.status_code == 200, first.text
        repeated = client.post(path, json=_payload(), headers=headers)
        assert repeated.status_code == 200
        assert repeated.json() == first.json()
        changed = _payload()
        changed["form"]["programme"] = "Management"
        assert client.post(path, json=changed, headers=headers).status_code == 409
        done = client.post(path + "/portal-app-1/1/complete", headers=headers)
        assert done.status_code == 200, done.text
        evaluated = client.post(path + "/portal-app-1/1/evaluate", headers=headers)
        assert evaluated.status_code == 200
        assert evaluated.json()["state"] == "error", evaluated.json()
        assert evaluated.json()["error"] == "no_documents"
        next_version = client.post(path, json=_payload(2), headers=headers)
        assert next_version.status_code == 200, next_version.text
        assert next_version.json()["application_id"] == first.json()["application_id"]
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Application)) == 1
            assert db.scalar(select(func.count()).select_from(PortalSubmission)) == 2
    finally:
        settings.portal_shared_secret, settings.portal_owner_email = previous


def test_document_hash_version_and_completion(client, make_user, session_factory):
    user = make_user(Role.REVIEWER, email="portal-doc-service@example.org")
    settings = get_settings()
    previous = (settings.portal_shared_secret, settings.portal_owner_email)
    settings.portal_shared_secret = SecretStr("test-secret-value")
    settings.portal_owner_email = user.email
    headers = {"X-Portal-Secret": "test-secret-value"}
    content = factories.pdf()
    payload = _payload()
    payload["documents"] = [{"version_id": "portal-version-1", "document_id": "portal-document-1",
        "code": "explanation", "version": 1, "filename": "evidence.pdf", "mime": "application/pdf",
        "sha256": hashlib.sha256(content).hexdigest()}]
    path = "/api/v1/portal-intake/submissions"
    try:
        staged = client.post(path, json=payload, headers=headers)
        assert staged.status_code == 200, staged.text
        assert client.post(path + "/portal-app-1/1/complete", headers=headers).status_code == 409
        file_path = path + "/portal-app-1/1/documents/portal-version-1"
        assert client.put(file_path, content=b"tampered", headers=headers).status_code == 409
        first = client.put(file_path, content=content, headers=headers)
        assert first.status_code == 200, first.text
        retry = client.put(file_path, content=content, headers=headers)
        assert retry.status_code == 200 and retry.json() == first.json()
        assert client.post(path + "/portal-app-1/1/complete", headers=headers).status_code == 200
        evaluated = client.post(path + "/portal-app-1/1/evaluate", headers=headers)
        assert evaluated.status_code == 200
        assert evaluated.json()["state"] == "no_rules", evaluated.json()
        with session_factory() as db:
            analysis = db.scalar(select(EvidenceAnalysis).where(EvidenceAnalysis.application_id == staged.json()["application_id"]))
            keys = set(db.scalars(select(EvidenceFinding.group_key).where(EvidenceFinding.analysis_id == analysis.id)))
            assert "institution_name" in keys
            assert "date_of_birth" not in keys
            assert "person_name" not in keys
        replacement = factories.pdf(marker="replacement")
        next_payload = _payload(2)
        next_payload["documents"] = [{**payload["documents"][0], "version_id": "portal-version-2",
            "version": 2, "sha256": hashlib.sha256(replacement).hexdigest()}]
        staged_again = client.post(path, json=next_payload, headers=headers)
        assert staged_again.status_code == 200, staged_again.text
        assert staged_again.json()["application_id"] == staged.json()["application_id"]
        uploaded_again = client.put(path + "/portal-app-1/2/documents/portal-version-2",
            content=replacement, headers=headers)
        assert uploaded_again.status_code == 200, uploaded_again.text
        assert client.post(path + "/portal-app-1/2/complete", headers=headers).status_code == 200
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Application)) == 1
            assert db.scalar(select(func.count()).select_from(PortalSubmission)) == 2
            assert db.scalar(select(func.count()).select_from(PortalDocument)) == 2
    finally:
        settings.portal_shared_secret, settings.portal_owner_email = previous
