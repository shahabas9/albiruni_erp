"""Dev fixture data — a runnable script, not a migration.

Creates the tenant/company/roles/user/customers/items this skeleton's demo
narrative uses throughout (same tenant_018 / company_kozhikode / user_ahmed
naming as the blueprint's own Appendix B example, and the same customers
and items the frontend prototype used). Safe to re-run: skips if the tenant
already exists.

    backend/.venv/bin/python -m app.seed
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.deps import RequestContext
from app.core.dev_schema import ensure_dev_schema
from app.core.security import hash_password
from app.domain import activity_service, crm_service, lead_service, opportunity_service
from app.domain.sales_service import persist_quotation, price_quotation
from app.models.crm import Lead
from app.models.identity import Role, User
from app.models.sales import Customer, Item
from app.models.tenant import Company, Tenant
from app.schemas import crm


# Everything the CRM pages and the Customers page check, including reassigning owners.
CRM_PERMISSIONS = [
    "crm.lead.read", "crm.lead.write", "crm.lead.convert", "crm.lead.assign",
    "crm.contact.read", "crm.contact.write",
    "crm.opportunity.read", "crm.opportunity.write", "crm.opportunity.assign",
    "crm.activity.read", "crm.activity.write",
    "crm.settings.write", "crm.records.all",
    "crm.lead.delete", "crm.opportunity.delete", "sales.customer.delete", "crm.export",
    "sales.customer.read", "sales.customer.write",
]


def seed_crm(db: Session, tenant: Tenant) -> None:
    """Idempotent: grants CRM permissions to the seeded Sales Manager and adds
    demo leads/opportunities/activities once. Safe on a DB seeded before CRM existed."""

    role = db.execute(select(Role).where(Role.tenant_id == tenant.id, Role.name == "Sales Manager")).scalar_one()
    missing = [p for p in CRM_PERMISSIONS if p not in role.permissions]
    if missing:
        role.permissions = [*role.permissions, *missing]

    if db.execute(select(Lead).where(Lead.tenant_id == tenant.id)).first() is not None:
        return

    ahmed = db.execute(select(User).where(User.username == "ahmed")).scalar_one()
    context = RequestContext(
        user=ahmed, tenant_id=tenant.id, company_id=ahmed.company_id, permissions=role.permissions, locale="en-IN"
    )
    now = crm_service.now_utc()

    fresh = lead_service.create_lead(db, context, crm.LeadIn(
        name="Shafeeq K", company_name="Calicut Build Mart", phone="+91 98470 11223", source="Walk-in",
    ))
    activity_service.create_activity(db, context, crm.ActivityIn(
        type="Call", subject="Intro call — pricing for Product A", due_at=now - timedelta(days=2), lead_id=fresh.id,
    ))
    lead_service.create_lead(db, context, crm.LeadIn(
        name="Nisha R", company_name="Kannur Tiles & Co", phone="+91 94460 44556",
        email="nisha@kannurtiles.example", source="Referral", owner_user_id=ahmed.id,
    ))

    qualified = lead_service.create_lead(db, context, crm.LeadIn(
        name="Faisal", company_name="Al Faisal Trading", source="Existing customer", owner_user_id=ahmed.id,
    ))
    _, _, _, opp = lead_service.convert_lead(db, context, qualified.id, crm.ConvertLeadIn(
        opportunity_name="Al Faisal — Q4 restock", opportunity_value=180_000,
        expected_close_date=date.today() + timedelta(days=21),
    ))
    activity_service.create_activity(db, context, crm.ActivityIn(
        type="Meeting", subject="Walk through Q4 volumes", due_at=now + timedelta(days=1), opportunity_id=opp.id,
    ))

    malabar = crm_service.find_or_create_customer(db, context, "Malabar Hardware")
    opportunity_service.create_opportunity(db, context, crm.OpportunityIn(
        customer_id=malabar.id, name="Malabar Hardware — branch expansion", value=450_000,
        expected_close_date=date.today() + timedelta(days=45),
    ))


def run() -> None:
    ensure_dev_schema()
    db: Session = SessionLocal()
    try:
        existing = db.execute(select(Tenant).where(Tenant.code == "tenant_018")).scalar_one_or_none()
        if existing is not None:
            print("Seed data already present (tenant_018) — topping up CRM only.")
            seed_crm(db, existing)
            db.commit()
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
                *CRM_PERMISSIONS,
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

        seed_crm(db, tenant)

        db.commit()
        print("Seeded tenant_018 / company_kozhikode with user 'ahmed' (password: ahmed123).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
