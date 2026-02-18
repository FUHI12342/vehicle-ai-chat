from fastapi import APIRouter

from app.llm.registry import provider_registry

router = APIRouter()


@router.get("/health")
async def health_check():
    active = provider_registry.get_active()
    return {
        "status": "ok",
        "llm_provider": active.name if active else None,
        "llm_configured": active.is_configured() if active else False,
    }
