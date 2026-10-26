"""Role-based access control.

Permissions are coarse capabilities checked on every protected endpoint via
``require_permission``. Resource-level rules (ownership) live in ``app.core.authz``.
The frontend receives the permission list only to shape navigation; the backend
remains the sole authority.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    COMPLIANCE_MANAGER = "compliance_manager"
    SECOND_APPROVER = "second_approver"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"


class Permission(StrEnum):
    USERS_MANAGE = "users:manage"
    USERS_READ = "users:read"
    SESSIONS_MANAGE = "sessions:manage"  # revoke other users' sessions
    AUDIT_READ = "audit:read"
    APPLICATIONS_READ = "applications:read"  # own / assigned applications
    APPLICATIONS_READ_ALL = "applications:read_all"  # every application, regardless of owner
    APPLICATIONS_WRITE = "applications:write"
    DOCUMENTS_UPLOAD = "documents:upload"
    DOCUMENTS_READ = "documents:read"
    RULES_READ = "rules:read"
    RULES_MANAGE = "rules:manage"
    RULES_PUBLISH = "rules:publish"
    RULES_SIMULATE = "rules:simulate"
    VALIDATION_RUN = "validation:run"
    REVIEW_RESOLVE = "review:resolve"
    SYSTEM_READ = "system:read"
    EXPORTS_CREATE = "exports:create"  # download metrics, audit, review, validation and rule history as CSV/JSON
    EXPORTS_SENSITIVE = "exports:sensitive"  # also extracted document values (still never raw page text)


P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Technical administration can inspect its institution's cases and metrics, but cannot edit cases or decide findings.
    Role.ADMIN: frozenset({P.USERS_MANAGE, P.USERS_READ, P.SESSIONS_MANAGE, P.AUDIT_READ, P.SYSTEM_READ,
                          P.APPLICATIONS_READ, P.APPLICATIONS_READ_ALL, P.DOCUMENTS_READ, P.RULES_READ,
                          P.EXPORTS_CREATE}),
    # Owns the compliance programme: rules, oversight of all applications, audit access.
    Role.COMPLIANCE_MANAGER: frozenset(
        {
            P.USERS_READ, P.AUDIT_READ, P.APPLICATIONS_READ, P.APPLICATIONS_READ_ALL, P.APPLICATIONS_WRITE,
            P.DOCUMENTS_UPLOAD, P.DOCUMENTS_READ, P.RULES_READ, P.RULES_MANAGE, P.RULES_SIMULATE,
            P.VALIDATION_RUN, P.REVIEW_RESOLVE, P.SYSTEM_READ, P.EXPORTS_CREATE, P.EXPORTS_SENSITIVE,
        }
    ),
    Role.SECOND_APPROVER: frozenset(
        {P.RULES_READ, P.RULES_PUBLISH, P.RULES_SIMULATE, P.APPLICATIONS_READ,
         P.APPLICATIONS_READ_ALL, P.AUDIT_READ, P.SYSTEM_READ}
    ),
    # Works cases: creates applications, uploads evidence, runs validation and resolves findings
    # on applications they own or are assigned to.
    Role.REVIEWER: frozenset(
        {
            P.APPLICATIONS_READ, P.APPLICATIONS_WRITE, P.DOCUMENTS_UPLOAD, P.DOCUMENTS_READ,
            P.RULES_READ, P.VALIDATION_RUN, P.REVIEW_RESOLVE, P.SYSTEM_READ,
        }
    ),
    # Strictly read-only, but across everything, for independent oversight.
    Role.AUDITOR: frozenset(
        {
            P.USERS_READ, P.AUDIT_READ, P.APPLICATIONS_READ, P.APPLICATIONS_READ_ALL, P.DOCUMENTS_READ,
            P.RULES_READ, P.SYSTEM_READ, P.EXPORTS_CREATE,
        }
    ),
}

ROLE_VALUES = tuple(r.value for r in Role)
# The legacy database CHECK covers four values. The fifth role is stored in a
# separate nullable column, avoiding a destructive SQLite users-table rebuild.
LEGACY_ROLE_VALUES = tuple(r.value for r in Role if r is not Role.SECOND_APPROVER)


def permissions_for(role: str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def has_permission(role: str, permission: Permission) -> bool:
    return permission in permissions_for(role)
