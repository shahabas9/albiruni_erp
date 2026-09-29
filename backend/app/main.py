from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.dev_schema import ensure_dev_schema

# Import routers
from app.api import routes_ask, routes_audit, routes_auth, routes_crm, routes_sales, routes_setup

# Import tool modules for their registration side effect (each module calls
# register_tool() at import time). This is the whole tool catalog today;
# new domains add a module here and nowhere else needs to change.
from app.toolgateway import tools_sales  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only — a real deployment manages schema via Alembic
    # migrations (see backend/alembic), never create_all().
    ensure_dev_schema()
    yield


app = FastAPI(title="Albiruni ERP API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_setup.router)
app.include_router(routes_auth.router)
app.include_router(routes_sales.router)
app.include_router(routes_crm.router)
app.include_router(routes_ask.router)
app.include_router(routes_audit.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
