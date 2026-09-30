import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.models.crm import SavedView
from app.models.identity import User

router = APIRouter(prefix="/api/views", tags=["crm"])

PAGES = ("leads", "opportunities", "customers", "contacts", "activities")
MAX_VIEWS_PER_PAGE = 30


def _check_filters(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value)) > 2000:
        raise ValueError("Those filters are too long to save.")
    for k, v in value.items():
        if not isinstance(k, str) or len(k) > 40 or not (v is None or isinstance(v, (str, bool, int, float))):
            raise ValueError("Filters must be simple values.")
    return value


class ViewIn(BaseModel):
    page: str
    name: str = Field(min_length=1, max_length=60)
    filters: dict[str, Any] = {}
    shared: bool = False

    _filters = field_validator("filters")(_check_filters)


class ViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    filters: dict[str, Any] | None = None
    shared: bool | None = None

    @field_validator("filters")
    @classmethod
    def _f(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _check_filters(value)


class ViewOut(BaseModel):
    id: UUID
    page: str
    name: str
    filters: dict[str, Any]
    shared: bool
    mine: bool
    owner_name: str | None
    created_at: datetime


def _out(v: SavedView, context: RequestContext, owner_name: str | None) -> ViewOut:
    return ViewOut(id=v.id, page=v.page, name=v.name, filters=v.filters or {}, shared=v.shared,
                   mine=v.user_id == context.user.id, owner_name=owner_name, created_at=v.created_at)


def _get(db: Session, context: RequestContext, view_id: UUID) -> SavedView:
    view = db.get(SavedView, view_id)
    if view is None or view.company_id != context.company_id or view.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such view.")
    return view


@router.get("", response_model=list[ViewOut])
def list_views(
    page: str,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Your views for a list page, plus the ones colleagues shared."""

    rows = db.execute(
        select(SavedView, User.display_name)
        .join(User, User.id == SavedView.user_id)
        .where(SavedView.tenant_id == context.tenant_id, SavedView.company_id == context.company_id,
               SavedView.page == page, or_(SavedView.user_id == context.user.id, SavedView.shared.is_(True)))
        .order_by(SavedView.name)
    ).all()
    return [_out(v, context, name) for v, name in rows]


@router.post("", response_model=ViewOut)
def create_view(
    body: ViewIn,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    if body.page not in PAGES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"page must be one of: {', '.join(PAGES)}")
    mine = db.execute(select(SavedView).where(SavedView.user_id == context.user.id, SavedView.page == body.page)).scalars().all()
    if len(mine) >= MAX_VIEWS_PER_PAGE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"At most {MAX_VIEWS_PER_PAGE} views per page.")
    if any(v.name.lower() == body.name.strip().lower() for v in mine):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"You already have a view called “{body.name.strip()}”.")
    view = SavedView(tenant_id=context.tenant_id, company_id=context.company_id, user_id=context.user.id, page=body.page,
                     name=body.name.strip(), filters=body.filters, shared=body.shared)
    db.add(view)
    db.commit()
    db.refresh(view)
    return _out(view, context, context.user.display_name)


@router.patch("/{view_id}", response_model=ViewOut)
def update_view(
    view_id: UUID,
    body: ViewUpdate,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Only the person who saved a view can change it."""

    view = _get(db, context, view_id)
    if view.user_id != context.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its owner can change this view.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(view, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(view)
    return _out(view, context, context.user.display_name)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(
    view_id: UUID,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Its owner can delete a view; so can CRM admins (crm.settings.write), for shared ones."""

    view = _get(db, context, view_id)
    if view.user_id != context.user.id and not context.has_permission("crm.settings.write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its owner can delete this view.")
    db.delete(view)
    db.commit()
