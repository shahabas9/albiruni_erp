import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    """A customer business on the platform. Every other table hangs off tenant_id."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)


class Company(Base):
    """A legal entity / branch within a tenant. Quotations, stock etc. are scoped per company."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), default="INR")

    # Seller details printed on tax invoices (Sales → Company & GST).
    legal_name: Mapped[str] = mapped_column(String(160), default="")
    gstin: Mapped[str] = mapped_column(String(15), default="")
    # GST state code; decides CGST+SGST (same state) versus IGST.
    state_code: Mapped[str] = mapped_column(String(2), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    bank_details: Mapped[str] = mapped_column(Text, default="")
    invoice_terms: Mapped[str] = mapped_column(Text, default="")
    # Days until an invoice falls due when the customer has no terms of their own.
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    # Whether a delivery may take stock below zero.
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False)
