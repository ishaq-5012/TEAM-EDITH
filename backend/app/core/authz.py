"""Resource-level authorization (ownership) policy.

Role permissions answer "may this kind of user do X at all?". This module answers
"may *this* user act on *this* record?". Every service that loads a user-scoped
record must pass it through ``authorize_owned``.

Denials raise ``NotFoundError`` rather than a 403, so a caller cannot learn whether
someone else's record exists. Later modules (applications, documents, reviews)
implement ``OwnedResource`` and reuse the same policy.
"""

from __future__ import annotations

from typing import Protocol

from app.core.errors import NotFoundError
from app.core.roles import Permission, has_permission
from app.models.user import User


class OwnedResource(Protocol):
    def owner_ids(self) -> set[str]:
        """IDs of users who own or are assigned to this record."""
        ...


def can_access(user: User, resource: OwnedResource, *, override: Permission | None) -> bool:
    if user.id in resource.owner_ids():
        return True
    return override is not None and has_permission(user.role, override)


def authorize_owned(
    user: User, resource: OwnedResource | None, *, override: Permission | None, label: str = "Resource"
) -> None:
    """Raise NotFoundError unless the user owns the resource or holds the override permission."""
    if resource is None or not can_access(user, resource, override=override):
        raise NotFoundError(f"{label} not found")
