from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import new_correlation_id
from app.core.database import get_db
from app.core.deps import RequestContext, require_permission
from app.models.sales import Quotation
from app.schemas.sales import CreateQuotationIn, QuotationLineOut, QuotationOut
from app.toolgateway.executor import execute_tool

router = APIRouter(prefix="/api/sales", tags=["sales"])


def _to_out(q: Quotation) -> QuotationOut:
    return QuotationOut(
        id=q.id,
        number=q.number,
        customer_name=q.customer.name,
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
    context: RequestContext = Depends(require_permission("sales.quotation.read")),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Quotation)
        .where(Quotation.tenant_id == context.tenant_id, Quotation.company_id == context.company_id)
        .order_by(Quotation.created_at.desc())
    )
    quotations = db.execute(stmt).scalars().all()
    return [_to_out(q) for q in quotations]


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
