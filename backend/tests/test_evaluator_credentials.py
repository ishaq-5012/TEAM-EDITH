"""Public evaluator autofill exposes only explicitly enabled, valid walkthrough accounts."""

from app.core.config import get_settings
from app.core.roles import Role

API = "/api/v1/auth/evaluator-credentials"


def test_evaluator_autofill_is_opt_in_and_checks_live_passwords(client, make_user, tmp_path):
    settings = get_settings()
    previous = (settings.evaluator_autofill, settings.evaluator_accounts_file)
    credentials = tmp_path / "accounts.txt"
    credentials.write_text(
        "admin sih.admin@example.org password: Correct-Horse-42 institution DEFAULT\n"
        "reviewer reviewer.demo@example.org password: Correct-Horse-42 institution DEFAULT\n"
        "compliance_manager compliance.manager@example.org password: Correct-Horse-42 institution DEFAULT\n"
        "auditor auditor.demo@example.org password: stale-password institution DEFAULT\n",
        encoding="utf-8",
    )
    make_user(Role.ADMIN, email="sih.admin@example.org")
    make_user(Role.REVIEWER, email="reviewer.demo@example.org")
    make_user(Role.COMPLIANCE_MANAGER, email="compliance.manager@example.org")
    make_user(Role.AUDITOR, email="auditor.demo@example.org")
    try:
        settings.evaluator_accounts_file = credentials
        settings.evaluator_autofill = False
        assert client.get(API).status_code == 404
        settings.evaluator_autofill = True
        response = client.get(API)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert [a["role"] for a in response.json()["accounts"]] == ["admin", "reviewer", "compliance_manager"]
    finally:
        settings.evaluator_autofill, settings.evaluator_accounts_file = previous
