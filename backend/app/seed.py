"""Dev fixture data — a runnable script, not a migration.

Creates the tenant/company/roles/user/customers/items this skeleton's demo
narrative uses throughout (same tenant_018 / company_kozhikode / user_ahmed
naming as the blueprint's own Appendix B example, and the same customers
and items the frontend prototype used). Safe to re-run: skips if the tenant
already exists.

    backend/.venv/bin/python -m app.seed
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine
from app.core.deps import RequestContext
from app.core.security import hash_password
from app.domain.sales_service import persist_quotation, price_quotation
from app.models.identity import Role, User
from app.models.sales import Customer, Item
from app.models.tenant import Company, Tenant


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        existing = db.execute(select(Tenant).where(Tenant.code == "tenant_018")).scalar_one_or_none()
        if existing is not None:
            print("Seed data already present (tenant_018) — skipping.")
            return

        tenant = Tenant(name="Albiruni Trading Group", code="tenant_018")
        db.add(tenant)
        db.flush()

        company = Company(tenant_id=tenant.id, name="Kozhikode HQ", code="company_kozhikode", currency="INR")
        db.add(company)
        db.flush()

        sales_manager_role = Role(
            tenant_id=tenant.id,
            name="Sales Manager",
            permissions=[
                "sales.quotation.create",
                "sales.quotation.read",
                "sales.quotation.approve",
                "audit.read",
            ],
        )
        db.add(sales_manager_role)
        db.flush()

        ahmed = User(
            tenant_id=tenant.id,
            company_id=company.id,
            role_id=sales_manager_role.id,
            username="ahmed",
            display_name="Ahmed",
            hashed_password=hash_password("ahmed123"),
            locale="en-IN",
        )
        db.add(ahmed)
        db.flush()

        customers = {
            name: Customer(tenant_id=tenant.id, company_id=company.id, name=name, credit_limit=credit_limit)
            for name, credit_limit in [
                ("Rahman Traders", 200_000),
                ("Coastal Traders", 500_000),
                ("Malabar Hardware", 1_000_000),
                ("Al Faisal Trading", 300_000),
            ]
        }
        db.add_all(customers.values())

        items = [
            Item(tenant_id=tenant.id, company_id=company.id, sku="PRD-A", name="Product A", uom="box", unit_price=420, stock_qty=500),
            Item(tenant_id=tenant.id, company_id=company.id, sku="PRD-B", name="Product B", uom="box", unit_price=610, stock_qty=300),
            Item(tenant_id=tenant.id, company_id=company.id, sku="PRD-C", name="Product C", uom="box", unit_price=955, stock_qty=40),
        ]
        db.add_all(items)
        db.flush()

        context = RequestContext(
            user=ahmed,
            tenant_id=tenant.id,
            company_id=company.id,
            permissions=sales_manager_role.permissions,
            locale="en-IN",
        )

        seed_quote_1 = persist_quotation(
            db,
            context,
            price_quotation(
                db, context, "Coastal Traders", [{"item_name": "Product A", "qty": 100}, {"item_name": "Product B", "qty": 50}], 0
            ),
            created_by=ahmed.id,
        )
        seed_quote_1.status = "Sent"

        persist_quotation(
            db,
            context,
            price_quotation(db, context, "Malabar Hardware", [{"item_name": "Product A", "qty": 200}], 3),
            created_by=ahmed.id,
        )

        db.commit()
        print("Seeded tenant_018 / company_kozhikode with user 'ahmed' (password: ahmed123).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
