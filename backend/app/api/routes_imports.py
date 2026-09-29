from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.domain import import_service

router = APIRouter(prefix="/api/imports", tags=["imports"])

PERMISSION = {"leads": "crm.lead.write", "customers": "sales.customer.write"}


class ImportIn(BaseModel):
    csv: str


@router.post("/{kind}")
def import_csv(
    kind: str,
    body: ImportIn,
    commit: bool = False,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Validate a CSV of leads or customers. With ?commit=true, also create the
    valid rows (duplicates and invalid rows are skipped) in one transaction.
    Always call without commit first and show the user what will happen."""

    permission = PERMISSION.get(kind)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import leads or customers.")
    if not context.has_permission(permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {permission}")

    try:
        rows, columns = import_service.parse(kind, body.csv)
    except import_service.CsvImportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    import_service.validate(db, context, kind, rows)
    created = import_service.commit(db, context, kind, rows) if commit else 0

    return {
        "kind": kind,
        "columns": columns,
        "total": len(rows),
        "ok": sum(r.status == "ok" for r in rows),
        "duplicates": sum(r.status == "duplicate" for r in rows),
        "errors": sum(r.status == "error" for r in rows),
        "created": created,
        "committed": commit,
        "rows": [
            {"line": r.line, "status": r.status, "messages": r.messages,
             "values": {k: v for k, v in r.values.items() if k != "owner_user_id"}}
            for r in rows
        ],
    }
