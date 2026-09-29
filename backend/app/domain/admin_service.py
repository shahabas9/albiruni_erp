from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import SUPER_ADMIN_PERMISSION, RequestContext
from app.core.security import hash_password
from app.domain.errors import ConflictError, NotFoundError
from app.models.identity import Role, User
from app.schemas.admin import RoleIn, RoleUpdate, UserIn, UserUpdate


def list_roles(db: Session, context: RequestContext) -> list[Role]:
    stmt = select(Role).where(Role.tenant_id == context.tenant_id).order_by(Role.name)
    return list(db.execute(stmt).scalars().all())


def create_role(db: Session, context: RequestContext, body: RoleIn) -> Role:
    role = Role(tenant_id=context.tenant_id, name=body.name, permissions=body.permissions)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def _get_role_in_tenant(db: Session, context: RequestContext, role_id: UUID) -> Role:
    role = db.get(Role, role_id)
    if role is None or role.tenant_id != context.tenant_id:
        raise NotFoundError(f"No role with id {role_id}")
    return role


def update_role(db: Session, context: RequestContext, role_id: UUID, body: RoleUpdate) -> Role:
    role = _get_role_in_tenant(db, context, role_id)
    data = body.model_dump(exclude_unset=True)

    if "permissions" in data:
        losing_super_admin = (
            SUPER_ADMIN_PERMISSION in role.permissions and SUPER_ADMIN_PERMISSION not in data["permissions"]
        )
        if losing_super_admin:
            other_super_admin = db.execute(
                select(Role).where(
                    Role.tenant_id == context.tenant_id,
                    Role.id != role.id,
                    Role.permissions.any(SUPER_ADMIN_PERMISSION),
                )
            ).first()
            if other_super_admin is None:
                raise ConflictError(
                    "This is the last Super Admin role in this organization — "
                    "keep the '*' permission here, or create another Super Admin role first."
                )

    for field, value in data.items():
        setattr(role, field, value)
    db.commit()
    db.refresh(role)
    return role


def list_users(db: Session, context: RequestContext) -> list[tuple[User, str | None]]:
    stmt = (
        select(User, Role.name)
        .join(Role, Role.id == User.role_id)
        .where(User.tenant_id == context.tenant_id)
        .order_by(User.display_name)
    )
    return list(db.execute(stmt).all())


def create_user(db: Session, context: RequestContext, body: UserIn) -> User:
    _get_role_in_tenant(db, context, body.role_id)  # 404s if the role isn't this tenant's

    existing = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"Username '{body.username}' is already taken.")

    user = User(
        tenant_id=context.tenant_id,
        company_id=context.company_id,
        role_id=body.role_id,
        username=body.username,
        display_name=body.display_name,
        hashed_password=hash_password(body.password),
        locale=body.locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, context: RequestContext, user_id: UUID, body: UserUpdate) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != context.tenant_id:
        raise NotFoundError(f"No user with id {user_id}")

    data = body.model_dump(exclude_unset=True, exclude={"password"})
    if "role_id" in data:
        _get_role_in_tenant(db, context, data["role_id"])
    if data.get("active") is False and user.id == context.user.id:
        raise ConflictError("You can't deactivate your own account.")
    for field, value in data.items():
        setattr(user, field, value)
    if body.password:
        user.hashed_password = hash_password(body.password)

    db.commit()
    db.refresh(user)
    return user
