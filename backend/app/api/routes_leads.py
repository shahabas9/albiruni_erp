from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context, require_permission
from app.domain import bulk_service, crm_service, history, lead_service, opportunity_service, record_admin
from app.domain.duplicates import DuplicateError
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import Lead
from app.schemas.crm import (
    BulkIn,
    BulkOut,
    ConvertLeadIn,
    ConvertLeadOut,
    CustomerMatchOut,
    LeadIn,
    LeadOut,
    LeadUpdate,
    MergeIn,
    OwnerIn,
    TimelineEntry,
)

router = APIRouter(prefix="/api/leads", tags=["crm"])

ASSIGN = "crm.lead.assign"


def http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DuplicateError):
        # The UI lists the matches and offers "create anyway" (allow_duplicate).
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"message": str(exc), "duplicates": exc.matches}
        )
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _to_out(lead: Lead, stats: crm_service.FollowUpStats, owners: dict) -> LeadOut:
    return LeadOut(
        id=lead.id, name=lead.name, company_name=lead.company_name, email=lead.email, phone=lead.phone,
        source=lead.source, status=lead.status, notes=lead.notes, owner_user_id=lead.owner_user_id,
        owner_name=owners.get(lead.owner_user_id), converted_customer_id=lead.converted_customer_id,
        converted_opportunity_id=lead.converted_opportunity_id, created_at=lead.created_at,
        tags=list(lead.tags or []), custom=dict(lead.custom or {}),
        **stats.for_lead(lead.id),
    )


def _single_out(db: Session, context: RequestContext, lead: Lead) -> LeadOut:
    stats = crm_service.FollowUpStats(db, context, lead_ids=[lead.id])
    return _to_out(lead, stats, crm_service.owner_names(db, {lead.owner_user_id}))


@router.get("", response_model=list[LeadOut])
def list_leads(
    response: Response,
    q: str = "",
    status_: str = Query("", alias="status", description='A status, or "open" (not Converted/Lost)'),
    owner: str = Query("", description='"me", "unassigned" or a user id'),
    tag: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("crm.lead.read")),
    db: Session = Depends(get_db),
):
    """Newest first. The total matching count is in the X-Total-Count header."""

    try:
        leads, total = lead_service.list_leads(
            db, context, q=q, status=status_, owner=owner, tag=tag, limit=limit, offset=offset
        )
    except ConflictError as exc:
        raise http_error(exc) from exc
    response.headers["X-Total-Count"] = str(total)
    stats = crm_service.FollowUpStats(db, context, lead_ids=[lead.id for lead in leads])
    owners = crm_service.owner_names(db, {lead.owner_user_id for lead in leads})
    return [_to_out(lead, stats, owners) for lead in leads]


@router.get("/duplicates")
def lead_duplicates(
    context: RequestContext = Depends(require_permission("crm.lead.read")),
    db: Session = Depends(get_db),
):
    """Groups of open leads sharing a phone number or email — candidates to merge."""

    groups = record_admin.lead_duplicate_groups(db, context)
    owners = crm_service.owner_names(db, {lead.owner_user_id for g in groups for lead in g["leads"]})
    stats = crm_service.FollowUpStats(db, context, lead_ids=[lead.id for g in groups for lead in g["leads"]])
    return [{"reason": g["reason"], "leads": [_to_out(lead, stats, owners) for lead in g["leads"]]} for g in groups]


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: UUID,
    context: RequestContext = Depends(require_permission("crm.lead.read")),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, lead_service.get_lead(db, context, lead_id))
    except NotFoundError as exc:
        raise http_error(exc) from exc


@router.get("/{lead_id}/timeline", response_model=list[TimelineEntry])
def lead_timeline(
    lead_id: UUID,
    context: RequestContext = Depends(require_permission("crm.lead.read")),
    db: Session = Depends(get_db),
):
    """Who changed what on this lead, newest first — including its deal's
    history once converted."""

    try:
        lead = lead_service.get_lead(db, context, lead_id)
    except NotFoundError as exc:
        raise http_error(exc) from exc
    refs = [("lead", lead.id)]
    if lead.converted_opportunity_id and context.has_permission("crm.opportunity.read"):
        try:
            opportunity_service.get_opportunity(db, context, lead.converted_opportunity_id)  # visible to them?
            refs.append(("opportunity", lead.converted_opportunity_id))
        except NotFoundError:
            pass
    return history.timeline(db, context, refs)


@router.get("/{lead_id}/customer-matches", response_model=list[CustomerMatchOut])
def lead_customer_matches(
    lead_id: UUID,
    context: RequestContext = Depends(require_permission("crm.lead.convert")),
    db: Session = Depends(get_db),
):
    """Existing customers this lead may already be (same name, or a contact
    with its phone/email) — the convert form offers them instead of guessing."""

    try:
        return lead_service.customer_matches(db, context, lead_id)
    except NotFoundError as exc:
        raise http_error(exc) from exc


@router.post("", response_model=LeadOut)
def create_lead(
    body: LeadIn,
    context: RequestContext = Depends(require_permission("crm.lead.write")),
    db: Session = Depends(get_db),
):
    if body.owner_user_id not in (None, context.user.id) and not context.has_permission(ASSIGN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {ASSIGN}")
    try:
        return _single_out(db, context, lead_service.create_lead(db, context, body))
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: UUID,
    body: LeadUpdate,
    context: RequestContext = Depends(require_permission("crm.lead.write")),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, lead_service.update_lead(db, context, lead_id, body))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.patch("/{lead_id}/owner", response_model=LeadOut)
def assign_lead(
    lead_id: UUID,
    body: OwnerIn,
    context: RequestContext = Depends(require_permission(ASSIGN)),
    db: Session = Depends(get_db),
):
    try:
        return _single_out(db, context, lead_service.assign_lead(db, context, lead_id, body.owner_user_id))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(
    lead_id: UUID,
    context: RequestContext = Depends(require_permission("crm.lead.delete")),
    db: Session = Depends(get_db),
):
    """Removes a lead with its follow-ups and files. Converted leads are kept."""

    try:
        record_admin.delete_lead(db, context, lead_id)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.post("/{lead_id}/merge", response_model=LeadOut)
def merge_lead(
    lead_id: UUID,
    body: MergeIn,
    context: RequestContext = Depends(require_permission("crm.lead.delete")),
    db: Session = Depends(get_db),
):
    """Folds lead `remove_id` into this one (details, notes, tags, follow-ups,
    files and history), then removes it."""

    if not context.has_permission("crm.lead.write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: crm.lead.write")
    try:
        return _single_out(db, context, record_admin.merge_leads(db, context, lead_id, body.remove_id))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.post("/{lead_id}/convert", response_model=ConvertLeadOut)
def convert_lead(
    lead_id: UUID,
    body: ConvertLeadIn,
    context: RequestContext = Depends(require_permission("crm.lead.convert")),
    db: Session = Depends(get_db),
):
    """Turns a qualified Lead into a Customer + Contact (+ optionally an
    Opportunity), atomically. Once converted, a lead is a historical record,
    not an editable one."""

    try:
        lead, customer, contact, opportunity = lead_service.convert_lead(db, context, lead_id, body)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc

    return ConvertLeadOut(
        lead_id=lead.id,
        customer_id=customer.id,
        contact_id=contact.id,
        opportunity_id=opportunity.id if opportunity else None,
    )

@router.post("/bulk", response_model=BulkOut)
def bulk_lead(
    body: BulkIn,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Assign, add_tag, remove_tag, status or delete — each record checked like a single edit; refused ones are skipped with the reason."""

    try:
        return bulk_service.run(db, context, "lead", body.action, ids=body.ids, filters=body.filters,
                                value=body.value, lost_reason=body.lost_reason)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ConflictError as exc:
        raise http_error(exc) from exc

