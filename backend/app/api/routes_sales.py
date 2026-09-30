from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.api.routes_items import _to_out as item_out
from app.core.database import get_db
from app.core.deps import RequestContext, require_any_permission, require_permission
from app.domain import sales_settings, tax
from app.domain.errors import ConflictError
from app.models.sales import Item, Quotation
from app.schemas.sales import (
    CompanyProfile, CompanyProfileUpdate, CreateQuotationIn, ItemOut, QuotationLineOut, QuotationOut, StateOut,
)
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales", tags=["sales"])


def to_quotation_out(q: Quotation) -> QuotationOut:
    return QuotationOut(
        id=q.id,
        number=q.number,
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
        created_at=q.created_at,
        lines=[
            QuotationLineOut(
                item_name=line.item.name,
                qty=float(line.qty),
                unit_price=float(line.unit_price),
                line_total=float(line.line_total),
                hsn_code=line.hsn_code or "",
                gst_rate=float(line.gst_rate),
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
    return [to_quotation_out(q) for q in quotations]


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
        "lines": [line.model_dump() for line in body.lines],
        "discount_pct": body.discount_pct,
    }
    return execute_tool(
        db,
        context,
        "sales.create_quotation_draft.v1",
        args,
        request_text=f"[form] New quotation for {body.customer_name}",
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
