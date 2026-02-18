from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.chat import router as chat_router
from app.api.vehicles import router as vehicles_router
from app.api.providers import router as providers_router
from app.api.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(vehicles_router, tags=["vehicles"])
api_router.include_router(providers_router, tags=["providers"])
api_router.include_router(admin_router, tags=["admin"])
