from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.api.routes_items import _to_out as item_out
from app.core.database import get_db
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.domain import quotation_service, sales_dashboard, sales_settings, tax
from app.domain.errors import ConflictError, NotFoundError
from app.models.documents import SalesOrder
from app.models.sales import Item, Quotation
from app.schemas.sales import (
    CompanyProfile, CompanyProfileUpdate, CreateQuotationIn, ItemOut, QuotationActionIn, QuotationLineOut, QuotationOut,
    QuotationUpdate, StateOut,
)
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales", tags=["sales"])


def orders_for(db: Session, quotation_ids: list[UUID]) -> dict[UUID, tuple[UUID, str]]:
    """The live (not cancelled) order each quotation became."""

    if not quotation_ids:
        return {}
    rows = db.execute(select(SalesOrder.quotation_id, SalesOrder.id, SalesOrder.number).where(
        SalesOrder.quotation_id.in_(quotation_ids), SalesOrder.status != "Cancelled",
    )).all()
    return {qid: (oid, number) for qid, oid, number in rows}


def to_quotation_out(q: Quotation, order: tuple[UUID, str] | None = None) -> QuotationOut:
    return QuotationOut(
        id=q.id,
        number=q.number,
        customer_id=q.customer_id,
        customer_name=q.customer.name,
        opportunity_id=q.opportunity_id,
        opportunity_title=q.opportunity.title if q.opportunity else None,
        subtotal=float(q.subtotal),
        discount_pct=float(q.discount_pct),
        total=float(q.total),
        place_of_supply=q.place_of_supply or "",
        cgst=float(q.cgst),
        sgst=float(q.sgst),
        igst=float(q.igst),
        round_off=float(q.round_off),
        grand_total=float(q.grand_total),
        status=q.status,
        status_note=q.status_note or "",
        valid_until=q.valid_until,
        is_expired=quotation_service.is_expired(q),
        notes=q.notes or "",
        customer_gstin=q.customer.gstin or "",
        billing_address=q.customer.billing_address or "",
        created_by_name=q.creator.display_name if q.creator else None,
        order_id=order[0] if order else None,
        order_number=order[1] if order else None,
        created_at=q.created_at,
        lines=[
            QuotationLineOut(
                item_id=line.item_id,
                item_name=line.item.name,
                uom=line.item.uom,
                qty=float(line.qty),
                unit_price=float(line.unit_price),
                line_total=float(line.line_total),
                hsn_code=line.hsn_code or "",
                gst_rate=float(line.gst_rate),
                discount_pct=float(line.discount_pct or 0),
                taxable_value=float(line.taxable_value),
                tax_amount=float(line.tax_amount),
            )
            for line in q.lines
        ],
    )


@router.get("/quotations", response_model=list[QuotationOut])
def list_quotations(
    customer_id: UUID | None = None,
    context: RequestContext = Depends(require_permission("sales.quotation.read")),
    db: Session = Depends(get_db),
):
    """Newest first; `customer_id` for one customer's quotations."""

    stmt = (
        select(Quotation)
        .where(Quotation.tenant_id == context.tenant_id, Quotation.company_id == context.company_id)
        .order_by(Quotation.created_at.desc())
    )
    if customer_id is not None:
        stmt = stmt.where(Quotation.customer_id == customer_id)
    quotations = db.execute(stmt).scalars().all()
    orders = orders_for(db, [q.id for q in quotations])
    return [to_quotation_out(q, orders.get(q.id)) for q in quotations]


@router.get("/quotations/{quotation_id}", response_model=QuotationOut)
def get_quotation(
    quotation_id: UUID,
    context: RequestContext = Depends(require_permission("sales.quotation.read")),
    db: Session = Depends(get_db),
):
    try:
        q = quotation_service.get_quotation(db, context, quotation_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return to_quotation_out(q, orders_for(db, [q.id]).get(q.id))


@router.patch("/quotations/{quotation_id}", response_model=QuotationOut)
def update_quotation(
    quotation_id: UUID,
    body: QuotationUpdate,
    context: RequestContext = Depends(require_permission("sales.quotation.create")),
    db: Session = Depends(get_db),
):
    """Edit a draft (re-priced; a discount over the limit or a price below list sends it back for approval).
    A sent quotation can only have its validity extended."""

    try:
        q, _ = quotation_service.update_quotation(db, context, quotation_id, body)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return to_quotation_out(q, orders_for(db, [q.id]).get(q.id))


@router.post("/quotations/{quotation_id}/{action}", response_model=QuotationOut)
def quotation_action(
    quotation_id: UUID,
    action: Literal["approve", "send", "accept", "reject", "reopen"],
    body: QuotationActionIn,
    context: RequestContext = Depends(require_permission("sales.quotation.create")),
    db: Session = Depends(get_db),
):
    """Approve (needs sales.quotation.approve), send, accept, reject (with a reason) or reopen."""

    try:
        q = quotation_service.change_status(db, context, quotation_id, action, body.note)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return to_quotation_out(q, orders_for(db, [q.id]).get(q.id))


@router.get("/items", response_model=list[ItemOut])
def list_items(
    context: RequestContext = Depends(require_permission("sales.quotation.read")),
    db: Session = Depends(get_db),
):
    """The price list a quotation form picks lines from."""

    stmt = (
        select(Item)
        .where(Item.tenant_id == context.tenant_id, Item.company_id == context.company_id)
        .order_by(Item.name)
    )
    return [item_out(i) for i in db.execute(stmt).scalars()]


@router.post("/quotations")
def create_quotation(
    body: CreateQuotationIn,
    context: RequestContext = Depends(require_permission("sales.quotation.create")),
    db: Session = Depends(get_db),
):
    """The conventional-UI path: a filled-in form, submitted directly.

    Runs through the identical tool the Ask ERP confirm step uses — the
    architecture has exactly one way to create a quotation, not two.
    """

    args = {
        "customer_name": body.customer_name,
        "customer_id": str(body.customer_id) if body.customer_id else None,
        "lines": [line.model_dump(mode="json", exclude_none=True) for line in body.lines],
        "discount_pct": body.discount_pct,
        "valid_until": body.valid_until.isoformat() if body.valid_until else None,
        "notes": body.notes,
    }
    return execute_tool(
        db,
        context,
        "sales.create_quotation_draft.v1",
        args,
        request_text=f"[form] New quotation for {body.customer_name or 'a customer'}",
        intent="sales.create_quotation",
        correlation_id=new_correlation_id(),
        confirmed=True,
    )


# --- Company & GST ---------------------------------------------------------------


@router.get("/states", response_model=list[StateOut])
def list_states():
    """GST state codes, for pickers."""

    return [StateOut(code=code, name=name) for code, name in tax.STATES.items()]


@router.get("/company", response_model=CompanyProfile)
def get_company_profile(
    context: RequestContext = Depends(require_any_permission("sales.quotation.read", "sales.settings.write")),
    db: Session = Depends(get_db),
):
    return sales_settings.profile(db, context)


@router.put("/company", response_model=CompanyProfile)
def update_company_profile(
    body: CompanyProfileUpdate,
    context: RequestContext = Depends(require_permission("sales.settings.write")),
    db: Session = Depends(get_db),
):
    try:
        return sales_settings.update_profile(db, context, body)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/dashboard")
def dashboard(
    context: RequestContext = Depends(require_any_permission("sales.invoice.read", "sales.order.read",
                                                             "sales.quotation.read")),
    db: Session = Depends(get_db),
):
    """Overview figures: invoiced and collected this month, what's owed and overdue, the last six
    months, top customers this financial year, orders to invoice and quotes awaiting a reply. Each
    block is present only with permission to read what's behind it."""

    return sales_dashboard.dashboard(db, context)
