from fastapi import APIRouter, Query

from app.services.vehicle_service import vehicle_service

router = APIRouter()


@router.get("/vehicles/search")
async def search_vehicles(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    results = vehicle_service.search(q, limit=limit)
    return {"results": [r.model_dump() for r in results]}
