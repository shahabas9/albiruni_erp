"""tax regimes india and saudi arabia

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02 04:19:47.571937
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.add_column('companies', sa.Column('country', sa.String(length=2), server_default='IN', nullable=False))
    op.add_column('companies', sa.Column('fy_start_month', sa.Integer(), server_default='4', nullable=False))
    op.add_column('companies', sa.Column('vat_number', sa.String(length=15), server_default='', nullable=False))
    op.add_column('companies', sa.Column('cr_number', sa.String(length=20), server_default='', nullable=False))
    op.add_column('companies', sa.Column('name_ar', sa.String(length=160), server_default='', nullable=False))
    op.add_column('companies', sa.Column('building_no', sa.String(length=10), server_default='', nullable=False))
    op.add_column('companies', sa.Column('street', sa.String(length=160), server_default='', nullable=False))
    op.add_column('companies', sa.Column('district', sa.String(length=120), server_default='', nullable=False))
    op.add_column('companies', sa.Column('city', sa.String(length=120), server_default='', nullable=False))
    op.add_column('companies', sa.Column('postal_code', sa.String(length=10), server_default='', nullable=False))
    op.add_column('credit_note_lines', sa.Column('tax_category', sa.String(length=1), server_default='', nullable=False))
    op.add_column('credit_note_lines', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('credit_notes', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('customers', sa.Column('country', sa.String(length=2), server_default='', nullable=False))
    op.add_column('customers', sa.Column('vat_number', sa.String(length=15), server_default='', nullable=False))
    op.add_column('customers', sa.Column('name_ar', sa.String(length=160), server_default='', nullable=False))
    op.add_column('customers', sa.Column('building_no', sa.String(length=10), server_default='', nullable=False))
    op.add_column('customers', sa.Column('street', sa.String(length=160), server_default='', nullable=False))
    op.add_column('customers', sa.Column('district', sa.String(length=120), server_default='', nullable=False))
    op.add_column('customers', sa.Column('city', sa.String(length=120), server_default='', nullable=False))
    op.add_column('customers', sa.Column('postal_code', sa.String(length=10), server_default='', nullable=False))
    op.add_column('invoice_lines', sa.Column('tax_category', sa.String(length=1), server_default='', nullable=False))
    op.add_column('invoice_lines', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('invoices', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('invoices', sa.Column('invoice_kind', sa.String(length=12), server_default='', nullable=False))
    op.add_column('invoices', sa.Column('seller_vat_number', sa.String(length=15), server_default='', nullable=False))
    op.add_column('invoices', sa.Column('buyer_vat_number', sa.String(length=15), server_default='', nullable=False))
    op.add_column('items', sa.Column('tax_category', sa.String(length=1), server_default='', nullable=False))
    op.add_column('items', sa.Column('exemption_reason', sa.String(length=20), server_default='', nullable=False))
    op.add_column('quotation_lines', sa.Column('tax_category', sa.String(length=1), server_default='', nullable=False))
    op.add_column('quotations', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('sales_order_lines', sa.Column('tax_category', sa.String(length=1), server_default='', nullable=False))
    op.add_column('sales_order_lines', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))
    op.add_column('sales_orders', sa.Column('vat', sa.Numeric(precision=14, scale=2), server_default='0', nullable=False))



def downgrade() -> None:

    op.drop_column('sales_orders', 'vat')
    op.drop_column('sales_order_lines', 'vat')
    op.drop_column('sales_order_lines', 'tax_category')
    op.drop_column('quotations', 'vat')
    op.drop_column('quotation_lines', 'tax_category')
    op.drop_column('items', 'exemption_reason')
    op.drop_column('items', 'tax_category')
    op.drop_column('invoices', 'buyer_vat_number')
    op.drop_column('invoices', 'seller_vat_number')
    op.drop_column('invoices', 'invoice_kind')
    op.drop_column('invoices', 'vat')
    op.drop_column('invoice_lines', 'vat')
    op.drop_column('invoice_lines', 'tax_category')
    op.drop_column('customers', 'postal_code')
    op.drop_column('customers', 'city')
    op.drop_column('customers', 'district')
    op.drop_column('customers', 'street')
    op.drop_column('customers', 'building_no')
    op.drop_column('customers', 'name_ar')
    op.drop_column('customers', 'vat_number')
    op.drop_column('customers', 'country')
    op.drop_column('credit_notes', 'vat')
    op.drop_column('credit_note_lines', 'vat')
    op.drop_column('credit_note_lines', 'tax_category')
    op.drop_column('companies', 'postal_code')
    op.drop_column('companies', 'city')
    op.drop_column('companies', 'district')
    op.drop_column('companies', 'street')
    op.drop_column('companies', 'building_no')
    op.drop_column('companies', 'name_ar')
    op.drop_column('companies', 'cr_number')
    op.drop_column('companies', 'vat_number')
    op.drop_column('companies', 'fy_start_month')
    op.drop_column('companies', 'country')

