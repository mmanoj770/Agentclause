import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import pool
from app.users.router import router as users_router

# INFO lines from our own code (intake usage, startup mode) are dropped unless a handler exists:
# uvicorn only configures its own loggers. Scoped to "app" so libraries keep their default level.
_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _app_logger.addHandler(_handler)
    _app_logger.setLevel(logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_startup()
    pool.open()
    try:
        from app.pipeline.runner import recover_stale_reviews
        with pool.connection(timeout=0.1) as conn:
            recover_stale_reviews(conn)
    except Exception:
        # Don't fail server startup if database is not reachable yet or unmigrated
        pass
    yield
    pool.close()

app = FastAPI(title="AgentClause API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(users_router)
from app.documents.router import router as documents_router
app.include_router(documents_router)
from app.lawyer_queue.router import router as queue_router
app.include_router(queue_router)
from app.findings.router import router as findings_router
app.include_router(findings_router)
from app.storage.router import router as storage_router
app.include_router(storage_router)
from app.agents.router import router as agents_router
app.include_router(agents_router)
from app.intake.router import router as intake_router
app.include_router(intake_router)
from app.rules.api import router as reviews_router
app.include_router(reviews_router)
