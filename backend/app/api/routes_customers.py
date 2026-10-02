from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import RequestContext, get_current_context, require_permission
from app.domain import bulk_service, crm_service, customer_service, history, receivables, record_admin
from app.api.routes_leads import http_error
from app.domain.errors import ConflictError, NotFoundError
from app.models.crm import OPEN_STAGES, Contact, Lead, Opportunity
from app.models.sales import Quotation
from app.schemas.crm import BulkIn, BulkOut, MergeIn, TimelineEntry
from app.schemas.customers import CustomerIn, CustomerOut, CustomerUpdate

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _to_out(c) -> CustomerOut:
    return CustomerOut(
        id=c.id, name=c.name, credit_limit=float(c.credit_limit), active=c.active, gstin=c.gstin,
        tags=list(c.tags or []), custom=dict(c.custom or {}), billing_address=c.billing_address or "",
        shipping_address=c.shipping_address or "", state_code=c.state_code or "",
        payment_terms_days=c.payment_terms_days, email=c.email or "", phone=c.phone or "",
        price_list_id=c.price_list_id, country=c.country or "", vat_number=c.vat_number or "",
        name_ar=c.name_ar or "", building_no=c.building_no or "", street=c.street or "", district=c.district or "",
        city=c.city or "", postal_code=c.postal_code or "",
    )


@router.get("", response_model=list[CustomerOut])
def list_customers(
    response: Response,
    q: str = "",
    active: bool | None = None,
    tag: str = "",
    limit: int | None = Query(None, ge=1, le=crm_service.MAX_PAGE),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    """By name. The total matching count is in the X-Total-Count header."""

    customers, total = customer_service.list_customers(
        db, context, q=q, active=active, tag=tag, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [_to_out(c) for c in customers]


@router.get("/duplicates")
def customer_duplicates(
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    """Groups of customers sharing a name or GSTIN — candidates to merge."""

    return [
        {"reason": g["reason"], "customers": [_to_out(c) for c in g["customers"]]}
        for g in record_admin.customer_duplicate_groups(db, context)
    ]


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: UUID,
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(customer_service.get_customer(db, context, customer_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{customer_id}/overview")
def customer_overview(
    customer_id: UUID,
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    """Headline numbers for the customer page. Deal figures only count deals
    the caller may see; quotation figures need sales.quotation.read."""

    try:
        customer = customer_service.get_customer(db, context, customer_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    deals = crm_service.only_visible(
        select(Opportunity.stage, func.count(), func.coalesce(func.sum(Opportunity.value), 0))
        .where(Opportunity.tenant_id == context.tenant_id, Opportunity.customer_id == customer.id),
        Opportunity.owner_user_id, context,
    ).group_by(Opportunity.stage)
    by_stage = {stage: (n, float(v)) for stage, n, v in db.execute(deals)}
    open_ = [by_stage.get(s, (0, 0.0)) for s in OPEN_STAGES]
    out = {
        "customer": _to_out(customer),
        "open_deals": sum(n for n, _ in open_),
        "open_value": sum(v for _, v in open_),
        "won_deals": by_stage.get("Won", (0, 0.0))[0],
        "won_value": by_stage.get("Won", (0, 0.0))[1],
        "lost_deals": by_stage.get("Lost", (0, 0.0))[0],
        "contacts": db.execute(select(func.count()).select_from(Contact).where(Contact.customer_id == customer.id)).scalar_one(),
        "quotations": None,
        "quoted_value": None,
    }
    if context.has_permission("sales.quotation.read"):
        count, total = db.execute(
            select(func.count(), func.coalesce(func.sum(Quotation.total), 0))
            .where(Quotation.tenant_id == context.tenant_id, Quotation.customer_id == customer.id)
        ).one()
        out["quotations"], out["quoted_value"] = count, float(total)
    out["account"] = None
    if context.has_permission("sales.invoice.read"):
        aged = next(iter(receivables.ageing(db, context, customer_id=customer.id)["rows"]), None)
        out["account"] = {
            "owed": aged["invoiced_owed"] if aged else 0.0, "overdue": aged["overdue"] if aged else 0.0,
            "advance": aged["advance"] if aged else 0.0, "net": aged["net"] if aged else 0.0,
            "open_invoices": aged["open_invoices"] if aged else 0, "oldest_due": aged["oldest_due"] if aged else None,
            "credit_limit": float(customer.credit_limit or 0),
        }
    return out


@router.get("/{customer_id}/timeline", response_model=list[TimelineEntry])
def customer_timeline(
    customer_id: UUID,
    context: RequestContext = Depends(require_permission("sales.customer.read")),
    db: Session = Depends(get_db),
):
    """The customer's own history plus that of its deals and the leads it
    came from — as far as the caller may see them."""

    try:
        customer = customer_service.get_customer(db, context, customer_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    refs = [("customer", customer.id)]
    if context.has_permission("crm.opportunity.read"):
        deals = crm_service.only_visible(
            select(Opportunity.id).where(Opportunity.tenant_id == context.tenant_id, Opportunity.customer_id == customer.id),
            Opportunity.owner_user_id, context,
        )
        refs += [("opportunity", i) for (i,) in db.execute(deals)]
    if context.has_permission("crm.lead.read"):
        leads = crm_service.only_visible(
            select(Lead.id).where(Lead.tenant_id == context.tenant_id, Lead.converted_customer_id == customer.id),
            Lead.owner_user_id, context,
        )
        refs += [("lead", i) for (i,) in db.execute(leads)]
    return history.timeline(db, context, refs)


@router.post("", response_model=CustomerOut)
def create_customer(
    body: CustomerIn,
    context: RequestContext = Depends(require_permission("sales.customer.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(customer_service.create_customer(db, context, body))
    except ConflictError as exc:  # duplicates, bad tags or custom values
        raise http_error(exc) from exc


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID,
    body: CustomerUpdate,
    context: RequestContext = Depends(require_permission("sales.customer.write")),
    db: Session = Depends(get_db),
):
    try:
        return _to_out(customer_service.update_customer(db, context, customer_id, body))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise http_error(exc) from exc


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: UUID,
    context: RequestContext = Depends(require_permission("sales.customer.delete")),
    db: Session = Depends(get_db),
):
    """Only customers with no deals, quotations or converted leads — merge the others."""

    try:
        record_admin.delete_customer(db, context, customer_id)
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc


@router.post("/{customer_id}/merge", response_model=CustomerOut)
def merge_customer(
    customer_id: UUID,
    body: MergeIn,
    context: RequestContext = Depends(require_permission("sales.customer.delete")),
    db: Session = Depends(get_db),
):
    """Moves everything of customer `remove_id` (contacts, deals, quotations,
    follow-ups, files, history) onto this one, then removes it."""

    try:
        return _to_out(record_admin.merge_customers(db, context, customer_id, body.remove_id))
    except (NotFoundError, ConflictError) as exc:
        raise http_error(exc) from exc

@router.post("/bulk", response_model=BulkOut)
def bulk_customer(
    body: BulkIn,
    context: RequestContext = Depends(get_current_context),
    db: Session = Depends(get_db),
):
    """Add_tag, remove_tag, activate, deactivate or delete — each record checked like a single edit; refused ones are skipped with the reason."""

    try:
        return bulk_service.run(db, context, "customer", body.action, ids=body.ids, filters=body.filters,
                                value=body.value, lost_reason=body.lost_reason)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ConflictError as exc:
        raise http_error(exc) from exc

