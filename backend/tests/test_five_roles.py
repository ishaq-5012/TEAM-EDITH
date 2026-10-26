"""Negative authorization checks for every officer role."""

from app.core.roles import Permission, Role, has_permission


def test_five_role_separation():
    assert set(Role) == {Role.ADMIN, Role.COMPLIANCE_MANAGER, Role.SECOND_APPROVER, Role.REVIEWER, Role.AUDITOR}
    for role in Role:
        assert has_permission(role, Permission.RULES_PUBLISH) is (role == Role.SECOND_APPROVER)
    for role in (Role.ADMIN, Role.SECOND_APPROVER, Role.AUDITOR, Role.REVIEWER):
        assert not has_permission(role, Permission.RULES_MANAGE)
    for role in (Role.ADMIN, Role.SECOND_APPROVER, Role.AUDITOR):
        assert not has_permission(role, Permission.REVIEW_RESOLVE)
        assert not has_permission(role, Permission.APPLICATIONS_WRITE)
    assert not has_permission(Role.AUDITOR, Permission.DOCUMENTS_UPLOAD)
    assert not has_permission(Role.REVIEWER, Permission.APPLICATIONS_READ_ALL)


def test_server_rejects_business_mutation_for_technical_and_read_only_roles(make_user, login):
    for role in (Role.ADMIN, Role.SECOND_APPROVER, Role.AUDITOR):
        user = make_user(role, email=f"negative-{role.value}@example.org")
        client = login(user.email)
        assert client.post("/api/v1/applications", json={"title": "Forbidden", "application_type": "demo"}).status_code == 403
        assert client.post("/api/v1/rules", json={}).status_code == 403
        assert client.get("/api/v1/auth/me").json()["role"] == role.value
