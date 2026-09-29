import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import SUPER_ADMIN_PERMISSION
from app.core.security import create_access_token, hash_password
from app.domain.identity_service import user_payload
from app.models.identity import Role, User
from app.models.tenant import Company, Tenant
from app.schemas.setup import BootstrapRequest, SetupStatus

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _slug(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "org"
    return f"{base[:28]}-{uuid.uuid4().hex[:6]}"


@router.get("/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db)):
    """The frontend calls this before showing Login — an empty `tenants`
    table means nobody has created the first Super Admin yet, so it shows
    the setup wizard instead."""

    tenant_count = db.execute(select(func.count()).select_from(Tenant)).scalar_one()
    return SetupStatus(needs_setup=tenant_count == 0)


@router.post("/bootstrap")
def bootstrap(body: BootstrapRequest, db: Session = Depends(get_db)):
    """Creates the first tenant, company, a Super Admin role (permission
    "*" — bypasses every permission check) and its user, then logs them in.

    Locks itself the moment any tenant exists: this is a one-time first-run
    wizard, never an open registration endpoint. Everyone after the first
    admin is created by that admin, through the normal product — not here.
    """

    existing = db.execute(select(func.count()).select_from(Tenant)).scalar_one()
    if existing > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already been completed for this deployment.",
        )

    username_taken = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if username_taken is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    tenant = Tenant(name=body.organization_name, code=_slug(body.organization_name))
    db.add(tenant)
    db.flush()

    company = Company(tenant_id=tenant.id, name=body.company_name, code=_slug(body.company_name), currency="INR")
    db.add(company)
    db.flush()

    super_admin_role = Role(tenant_id=tenant.id, name="Super Admin", permissions=[SUPER_ADMIN_PERMISSION])
    db.add(super_admin_role)
    db.flush()

    admin = User(
        tenant_id=tenant.id,
        company_id=company.id,
        role_id=super_admin_role.id,
        username=body.username,
        display_name=body.admin_name,
        hashed_password=hash_password(body.password),
        locale="en-IN",
    )
    db.add(admin)
    db.commit()

    token = create_access_token(subject=str(admin.id), extra_claims={"tenant_id": str(tenant.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_payload(db, admin),
    }
