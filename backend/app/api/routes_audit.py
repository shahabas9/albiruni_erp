from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.models.audit import AuditEvent
from app.models.identity import User
from app.schemas.audit import AuditEventOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/events", response_model=list[AuditEventOut])
def list_events(
    context: RequestContext = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    stmt = (
        select(AuditEvent, User.display_name)
        .join(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.tenant_id == context.tenant_id, AuditEvent.company_id == context.company_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return [
        AuditEventOut(
            id=event.id,
            correlation_id=event.correlation_id,
            actor=actor_name,
            intent=event.intent,
            risk_level=event.risk_level,
            tool_name=event.tool_name,
            validation_result=event.validation_result,
            confirmed=event.confirmed,
            result_summary=event.result_summary,
            created_at=event.created_at,
        )
        for event, actor_name in rows
    ]
