from pydantic import BaseModel


class ProviderInfo(BaseModel):
    name: str
    display_name: str
    is_configured: bool
    is_active: bool


class ProviderListResponse(BaseModel):
    providers: list[ProviderInfo]
    active: str


class SetActiveProviderRequest(BaseModel):
    provider: str
