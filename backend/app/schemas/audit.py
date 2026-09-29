from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: UUID
    correlation_id: str
    actor: str
    intent: str
    risk_level: str
    tool_name: str
    validation_result: str
    confirmed: bool
    result_summary: str
    created_at: datetime
