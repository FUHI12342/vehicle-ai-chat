from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import api_router
from app.llm.registry import provider_registry
from app.rag.vector_store import vector_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider_registry.initialize()
    vector_store.initialize()
    yield


app = FastAPI(title="Vehicle AI Chat", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
