from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.domain import admin_service
from app.domain.errors import ConflictError, NotFoundError
from app.models.identity import User
from app.schemas.admin import RoleIn, RoleOut, RoleUpdate, UserIn, UserOut, UserUpdate

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _role_out(r) -> RoleOut:
    return RoleOut(id=r.id, name=r.name, permissions=r.permissions)


def _user_out(row: tuple[User, str | None]) -> UserOut:
    user, role_name = row
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name, role_id=user.role_id,
        role_name=role_name, locale=user.locale, active=user.active,
    )


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    context: RequestContext = Depends(require_permission("admin.users.read")),
    db: Session = Depends(get_db),
):
    return [_role_out(r) for r in admin_service.list_roles(db, context)]


@router.post("/roles", response_model=RoleOut)
def create_role(
    body: RoleIn,
    context: RequestContext = Depends(require_permission("admin.users.write")),
    db: Session = Depends(get_db),
):
    return _role_out(admin_service.create_role(db, context, body))


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: UUID,
    body: RoleUpdate,
    context: RequestContext = Depends(require_permission("admin.users.write")),
    db: Session = Depends(get_db),
):
    try:
        return _role_out(admin_service.update_role(db, context, role_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/users", response_model=list[UserOut])
def list_users(
    context: RequestContext = Depends(require_permission("admin.users.read")),
    db: Session = Depends(get_db),
):
    return [_user_out(row) for row in admin_service.list_users(db, context)]


@router.post("/users", response_model=UserOut)
def create_user(
    body: UserIn,
    context: RequestContext = Depends(require_permission("admin.users.write")),
    db: Session = Depends(get_db),
):
    try:
        user = admin_service.create_user(db, context, body)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    role = next((r for r in admin_service.list_roles(db, context) if r.id == user.role_id), None)
    return _user_out((user, role.name if role else None))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    body: UserUpdate,
    context: RequestContext = Depends(require_permission("admin.users.write")),
    db: Session = Depends(get_db),
):
    try:
        user = admin_service.update_user(db, context, user_id, body)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    role = next((r for r in admin_service.list_roles(db, context) if r.id == user.role_id), None)
    return _user_out((user, role.name if role else None))
