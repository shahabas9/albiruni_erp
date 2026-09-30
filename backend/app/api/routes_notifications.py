from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.domain import notifications

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    link: str
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


class ReadIn(BaseModel):
    # Omit to mark everything read.
    ids: list[UUID] | None = None


class PreferencesIn(BaseModel):
    email: str | None = Field(default=None, max_length=160)
    notify_email: bool | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value and ("@" not in value or " " in value or "." not in value.split("@")[-1]):
            raise ValueError("That email address doesn't look right.")
        return value


class PreferencesOut(BaseModel):
    email: str
    notify_email: bool
    email_enabled: bool  # the server can send email at all (SMTP configured)


@router.get("", response_model=NotificationList)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Your notifications, newest first, with how many are unread."""

    return notifications.list_for(db, context, unread_only=unread_only, limit=limit)


@router.post("/read")
def mark_read(
    body: ReadIn,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    return {"marked": notifications.mark_read(db, context, body.ids)}


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(context: RequestContext = Depends(get_current_context)):
    return PreferencesOut(email=context.user.email or "", notify_email=context.user.notify_email,
                          email_enabled=notifications.smtp_configured())


@router.put("/preferences", response_model=PreferencesOut)
def put_preferences(
    body: PreferencesIn,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Where your notifications are emailed, and whether they are."""

    user = context.user
    if body.email is not None:
        user.email = body.email
    if body.notify_email is not None:
        user.notify_email = body.notify_email
    db.add(user)
    db.commit()
    return PreferencesOut(email=user.email, notify_email=user.notify_email, email_enabled=notifications.smtp_configured())
