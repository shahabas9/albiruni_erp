from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.models.sales import Item, Quotation
from app.schemas.sales import CreateQuotationIn, ItemOut, QuotationLineOut, QuotationOut
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
        status=q.status,
        created_at=q.created_at,
        lines=[
            QuotationLineOut(
                item_name=line.item.name,
                qty=float(line.qty),
                unit_price=float(line.unit_price),
                line_total=float(line.line_total),
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
    return [
        ItemOut(
            id=i.id, sku=i.sku, name=i.name, uom=i.uom, unit_price=float(i.unit_price), stock_qty=float(i.stock_qty)
        )
        for i in db.execute(stmt).scalars()
    ]


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
