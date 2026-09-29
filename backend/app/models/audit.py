import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    """Append-only record of every AI-initiated action, written only by the tool gateway.

    Mirrors the "AI audit event" contract from the blueprint (Section 5 /
    Appendix B): who asked, what was understood, which tool ran, what it
    was permitted to do, whether the user confirmed, and what happened.
    Nothing outside app.toolgateway.executor writes to this table.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    correlation_id: Mapped[str] = mapped_column(String(40))
    request_text: Mapped[str] = mapped_column(String(2000))
    intent: Mapped[str] = mapped_column(String(80))
    risk_level: Mapped[str] = mapped_column(String(20))
    tool_name: Mapped[str] = mapped_column(String(80))
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    arguments: Mapped[dict] = mapped_column(JSONB, default=dict)
    validation_result: Mapped[str] = mapped_column(String(400))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    result_summary: Mapped[str] = mapped_column(String(400))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
