"""Files attached to leads, deals and customers.

Bytes are written to disk (settings.attachments_dir/<tenant>/<id>) before the
row is committed and removed again if the commit fails, so a row never points
at a missing file. Downloads are always served as attachments (never rendered
inline), so an uploaded HTML or SVG file can't run in the app's origin.
"""

import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import RequestContext
from app.domain import history
from app.domain.customer_service import get_customer
from app.domain.errors import ConflictError, NotFoundError
from app.domain.lead_service import get_lead
from app.domain.opportunity_service import get_opportunity
from app.models.crm import Attachment
from app.models.identity import User

RECORD_TYPES = ("lead", "opportunity", "customer")
READ = {"lead": "crm.lead.read", "opportunity": "crm.opportunity.read", "customer": "sales.customer.read"}
WRITE = {"lead": "crm.lead.write", "opportunity": "crm.opportunity.write", "customer": "sales.customer.write"}
MAX_FILES_PER_RECORD = 50
CHUNK = 1024 * 1024
# Programs and scripts have no business in a CRM record.
BLOCKED_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif", ".cpl", ".ps1", ".psm1", ".vbs", ".vbe", ".js",
    ".jse", ".wsf", ".wsh", ".jar", ".sh", ".app", ".dll", ".hta", ".lnk", ".reg",
}


def max_bytes() -> int:
    return settings.attachment_max_mb * 1024 * 1024


def _root() -> Path:
    return Path(settings.attachments_dir)


def _path(attachment: Attachment) -> Path:
    return _root() / str(attachment.tenant_id) / str(attachment.id)


def clean_filename(name: str) -> str:
    """A display/download name without paths, control characters or quotes."""

    name = unicodedata.normalize("NFC", os.path.basename((name or "").replace("\\", "/")))
    name = re.sub(r'[\x00-\x1f\x7f"<>:|?*]', "", name).strip(" .")
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[: 200 - len(ext)] + ext
    return name or "file"


def check_record(db: Session, context: RequestContext, record_type: str, record_id: UUID, *, write: bool) -> None:
    """The record must exist in this company and the caller must be allowed
    to read it (or change it, for uploads and deletes). Raises NotFoundError,
    ConflictError or PermissionError."""

    if record_type not in RECORD_TYPES:
        raise ConflictError(f"Files can be attached to: {', '.join(RECORD_TYPES)}.")
    permission = (WRITE if write else READ)[record_type]
    if not context.has_permission(permission):
        raise PermissionError(f"Missing permission: {permission}")
    {"lead": get_lead, "opportunity": get_opportunity, "customer": get_customer}[record_type](db, context, record_id)


def list_attachments(db: Session, context: RequestContext, record_type: str, record_id: UUID) -> list[dict]:
    check_record(db, context, record_type, record_id, write=False)
    rows = db.execute(
        select(Attachment, User.display_name)
        .outerjoin(User, User.id == Attachment.uploaded_by)
        .where(
            Attachment.tenant_id == context.tenant_id, Attachment.company_id == context.company_id,
            Attachment.record_type == record_type, Attachment.record_id == record_id,
        )
        .order_by(Attachment.created_at.desc())
    ).all()
    return [to_dict(a, name) for a, name in rows]


def to_dict(a: Attachment, uploaded_by_name: str | None) -> dict:
    return {
        "id": a.id, "record_type": a.record_type, "record_id": a.record_id, "filename": a.filename,
        "content_type": a.content_type, "size_bytes": a.size_bytes, "uploaded_by_name": uploaded_by_name,
        "created_at": a.created_at,
    }


def get_attachment(db: Session, context: RequestContext, attachment_id: UUID, *, write: bool) -> Attachment:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.tenant_id != context.tenant_id or attachment.company_id != context.company_id:
        raise NotFoundError(f"No file with id {attachment_id}")
    check_record(db, context, attachment.record_type, attachment.record_id, write=write)
    return attachment


def save(
    db: Session, context: RequestContext, record_type: str, record_id: UUID, filename: str,
    content_type: str | None, stream: BinaryIO,
) -> dict:
    check_record(db, context, record_type, record_id, write=True)
    filename = clean_filename(filename)
    if os.path.splitext(filename)[1].lower() in BLOCKED_EXTENSIONS:
        raise ConflictError("Programs and scripts can't be attached.")
    count = db.execute(
        select(func.count()).select_from(Attachment).where(
            Attachment.tenant_id == context.tenant_id, Attachment.record_type == record_type,
            Attachment.record_id == record_id,
        )
    ).scalar_one()
    if count >= MAX_FILES_PER_RECORD:
        raise ConflictError(f"A record can have at most {MAX_FILES_PER_RECORD} files — remove some first.")

    folder = _root() / str(context.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    limit = max_bytes()
    size = 0
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise ConflictError(f"Files can be at most {settings.attachment_max_mb} MB.")
                out.write(chunk)
        if size == 0:
            raise ConflictError("That file is empty.")

        attachment = Attachment(
            id=uuid4(), tenant_id=context.tenant_id, company_id=context.company_id, record_type=record_type,
            record_id=record_id, filename=filename, content_type=(content_type or "application/octet-stream")[:120],
            size_bytes=size, uploaded_by=context.user.id,
        )
        db.add(attachment)
        if record_type in ("lead", "opportunity"):
            history.record(db, context, record_type, record_id, "file_attached", f"Attached {filename}")
        db.flush()
        os.replace(tmp, _path(attachment))
        tmp = None
        try:
            db.commit()
        except Exception:
            _path(attachment).unlink(missing_ok=True)
            raise
        db.refresh(attachment)
        return to_dict(attachment, context.user.display_name)
    finally:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)


def file_path(attachment: Attachment) -> Path:
    path = _path(attachment)
    if not path.is_file():
        raise NotFoundError("This file is missing from storage.")
    return path


def delete(db: Session, context: RequestContext, attachment_id: UUID) -> None:
    attachment = get_attachment(db, context, attachment_id, write=True)
    path = _path(attachment)
    if attachment.record_type in ("lead", "opportunity"):
        history.record(db, context, attachment.record_type, attachment.record_id, "file_removed",
                       f"Removed {attachment.filename}")
    db.delete(attachment)
    db.commit()
    path.unlink(missing_ok=True)  # after the commit: a failed delete keeps the file
