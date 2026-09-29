from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.routes_leads import http_error
from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context
from app.domain import attachment_service
from app.domain.errors import ConflictError, NotFoundError
from app.schemas.crm import AttachmentOut

router = APIRouter(prefix="/api/attachments", tags=["crm"])


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return http_error(exc)


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    record_type: str,
    record_id: UUID,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Files on a lead, opportunity or customer, newest first. Needs read
    permission on that record type."""

    try:
        return attachment_service.list_attachments(db, context, record_type, record_id)
    except (PermissionError, NotFoundError, ConflictError) as exc:
        raise _handle(exc) from exc


@router.post("", response_model=AttachmentOut)
def upload_attachment(
    record_type: str = Form(...),
    record_id: UUID = Form(...),
    file: UploadFile = File(...),
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Multipart upload (fields record_type, record_id, file). Needs write
    permission on the record type; programs and scripts are refused, and
    files are limited in size (ATTACHMENT_MAX_MB, default 10)."""

    try:
        return attachment_service.save(
            db, context, record_type, record_id, file.filename or "file", file.content_type, file.file
        )
    except (PermissionError, NotFoundError, ConflictError) as exc:
        raise _handle(exc) from exc


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: UUID,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    try:
        attachment = attachment_service.get_attachment(db, context, attachment_id, write=False)
        path = attachment_service.file_path(attachment)
    except (PermissionError, NotFoundError, ConflictError) as exc:
        raise _handle(exc) from exc
    # Always a download, never rendered: an uploaded HTML/SVG can't run as the app.
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=attachment.filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    attachment_id: UUID,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    try:
        attachment_service.delete(db, context, attachment_id)
    except (PermissionError, NotFoundError, ConflictError) as exc:
        raise _handle(exc) from exc
