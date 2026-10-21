from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import pool
from app.users.router import router as users_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
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
