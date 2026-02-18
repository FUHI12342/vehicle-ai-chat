from fastapi import APIRouter, HTTPException

from app.llm.registry import provider_registry
from app.models.provider import ProviderInfo, ProviderListResponse, SetActiveProviderRequest

router = APIRouter()


@router.get("/providers", response_model=ProviderListResponse)
async def list_providers():
    providers = []
    active_name = provider_registry.active_name
    for name, provider in provider_registry.providers.items():
        providers.append(
            ProviderInfo(
                name=provider.name,
                display_name=provider.display_name,
                is_configured=provider.is_configured(),
                is_active=(name == active_name),
            )
        )
    return ProviderListResponse(providers=providers, active=active_name)


@router.put("/providers/active")
async def set_active_provider(req: SetActiveProviderRequest):
    try:
        provider_registry.set_active(req.provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"active": req.provider}
