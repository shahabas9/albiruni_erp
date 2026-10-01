import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.migrations import upgrade_database
from app.domain import notifications
from app.core.public_cors import PublicCORSMiddleware

# Import routers
from app.api import (
    routes_activities,
    routes_attachments,
    routes_crm,
    routes_admin,
    routes_ask,
    routes_audit,
    routes_auth,
    routes_contacts,
    routes_customers,
    routes_deliveries,
    routes_exports,
    routes_imports,
    routes_invoices,
    routes_items,
    routes_leads,
    routes_notifications,
    routes_opportunities,
    routes_orders,
    routes_payments,
    routes_public,
    routes_receivables,
    routes_reports,
    routes_sales,
    routes_setup,
    routes_views,
)

# Import tool modules for their registration side effect (each module calls
# register_tool() at import time). This is the whole tool catalog today;
# new domains add a module here and nowhere else needs to change.
from app.toolgateway import tools_crm, tools_documents, tools_sales  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations run at startup unless AUTO_MIGRATE=0 (then run `alembic upgrade head` when deploying).
    if settings.auto_migrate:
        upgrade_database()
    worker = asyncio.create_task(_notification_worker()) if settings.notification_worker else None
    yield
    if worker:
        worker.cancel()


async def _notification_worker():
    """Overdue follow-up alerts and notification emails, every minute or so."""

    while True:
        await asyncio.sleep(settings.notification_interval_seconds)
        await asyncio.to_thread(notifications.run_worker_cycle)


app = FastAPI(title="Albiruni ERP API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Row-Count", "Content-Disposition"],  # paging totals, export downloads
)
# Added last, so it runs first: /api/public/* (the web enquiry form) is open to any origin.
app.add_middleware(PublicCORSMiddleware)

app.include_router(routes_setup.router)
app.include_router(routes_auth.router)
# Before routes_sales: /api/sales/quotations/{id}/order must win over /quotations/{id}/{action}.
app.include_router(routes_orders.router)
app.include_router(routes_deliveries.router)
app.include_router(routes_invoices.router)
app.include_router(routes_payments.router)
app.include_router(routes_receivables.router)
app.include_router(routes_reports.router)
app.include_router(routes_sales.router)
app.include_router(routes_ask.router)
app.include_router(routes_audit.router)
app.include_router(routes_customers.router)
app.include_router(routes_imports.router)
app.include_router(routes_items.router)
app.include_router(routes_admin.router)
app.include_router(routes_leads.router)
app.include_router(routes_contacts.router)
app.include_router(routes_opportunities.router)
app.include_router(routes_activities.router)
app.include_router(routes_activities.assignees_router)
app.include_router(routes_crm.router)
app.include_router(routes_attachments.router)
app.include_router(routes_public.router)
app.include_router(routes_notifications.router)
app.include_router(routes_exports.router)
app.include_router(routes_views.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
