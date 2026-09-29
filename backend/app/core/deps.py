from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.identity import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# A role holding this single permission string bypasses every permission
# check — the "Super Admin" role the setup wizard creates for the first
# user, same convention as any RBAC system's superuser flag. It is never
# implied by anything else and is only ever granted by the one-time
# bootstrap flow (see api/routes_setup.py) or by another Super Admin.
SUPER_ADMIN_PERMISSION = "*"


@dataclass
class RequestContext:
    """The 'screen context envelope' the blueprint describes: who is asking,
    on behalf of which tenant/company, in which language, with which
    permissions. Every domain service and tool call receives this instead
    of trusting raw request input for identity/authorization.
    """

    user: User
    tenant_id: UUID
    company_id: UUID
    permissions: list[str]
    locale: str

    def has_permission(self, permission: str) -> bool:
        return SUPER_ADMIN_PERMISSION in self.permissions or permission in self.permissions


def get_current_context(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> RequestContext:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.active:
        # Re-checked on every request (not just at login) so deactivating a
        # user ends their session immediately, even one already holding a
        # valid, unexpired token.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account has been deactivated")

    role = db.get(Role, user.role_id)
    permissions = role.permissions if role else []

    return RequestContext(
        user=user,
        tenant_id=user.tenant_id,
        company_id=user.company_id,
        permissions=permissions,
        locale=user.locale,
    )


def require_permission(permission: str):
    """Dependency factory: 403s unless the caller's role grants `permission`.

    Re-checked on every request from the DB-backed role — never cached on a
    token or trusted from client-supplied state — per the blueprint's
    "re-evaluate permissions at every tool call" rule.
    """

    def _check(context: RequestContext = Depends(get_current_context)) -> RequestContext:
        if not context.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return context

    return _check
