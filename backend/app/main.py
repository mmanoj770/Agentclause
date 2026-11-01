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
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(users_router)
from app.documents.router import router as documents_router
app.include_router(documents_router)
from app.lawyer_queue.router import router as queue_router
app.include_router(queue_router)

import os

from dotenv import load_dotenv

load_dotenv()
if os.environ.get("CHAT_STUB") == "1":
    from app.agents.conversational.stub_router import router as chat_stub_router

    app.include_router(chat_stub_router)
