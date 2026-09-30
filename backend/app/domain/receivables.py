"""What customers owe: outstanding invoices, advances, ageing and statements."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import RequestContext
from app.models.documents import Invoice, Receipt, ReceiptAllocation


def invoices_owed(db: Session, context: RequestContext, customer_id: UUID) -> Decimal:
    """Sum of issued invoices' balances (a credited-back invoice can count below zero)."""

    total = db.execute(select(func.coalesce(
        func.sum(Invoice.grand_total - Invoice.amount_paid - Invoice.amount_credited), 0,
    )).where(
        Invoice.tenant_id == context.tenant_id, Invoice.company_id == context.company_id,
        Invoice.customer_id == customer_id, Invoice.status == "Issued",
    )).scalar_one()
    return Decimal(str(total))


def advances(db: Session, context: RequestContext, customer_id: UUID) -> Decimal:
    """Money received and not yet applied to an invoice."""

    used = (select(func.coalesce(func.sum(ReceiptAllocation.amount), 0))
            .where(ReceiptAllocation.receipt_id == Receipt.id).scalar_subquery())
    total = db.execute(select(func.coalesce(func.sum(Receipt.amount - used), 0)).where(
        Receipt.tenant_id == context.tenant_id, Receipt.company_id == context.company_id,
        Receipt.customer_id == customer_id, Receipt.status == "Received",
    )).scalar_one()
    return Decimal(str(total))


def net_owed(db: Session, context: RequestContext, customer_id: UUID) -> Decimal:
    """What the customer owes after their advances; negative when we owe them."""

    return invoices_owed(db, context, customer_id) - advances(db, context, customer_id)
