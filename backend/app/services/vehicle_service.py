import json
from pathlib import Path

from app.models.vehicle import Vehicle, VehicleMatch


class VehicleService:
    def __init__(self):
        self._vehicles: list[Vehicle] = []
        self._load_vehicles()

    def _load_vehicles(self):
        data_path = Path(__file__).parent.parent / "data" / "vehicles.json"
        if data_path.exists():
            with open(data_path, encoding="utf-8") as f:
                data = json.load(f)
            self._vehicles = [Vehicle(**v) for v in data]

    def search(self, query: str, limit: int = 10) -> list[VehicleMatch]:
        query_lower = query.lower().strip()
        if not query_lower:
            return []

        results: list[VehicleMatch] = []
        for vehicle in self._vehicles:
            score = self._match_score(vehicle, query_lower)
            if score > 0:
                results.append(VehicleMatch(vehicle=vehicle, score=score))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def get_by_id(self, vehicle_id: str) -> Vehicle | None:
        for v in self._vehicles:
            if v.id == vehicle_id:
                return v
        return None

    def _match_score(self, vehicle: Vehicle, query: str) -> float:
        score = 0.0
        fields = [
            (vehicle.make.lower(), 3.0),
            (vehicle.model.lower(), 3.0),
            (str(vehicle.year), 2.0),
            (vehicle.trim.lower(), 1.0),
            (vehicle.id.lower(), 1.0),
        ]
        for value, weight in fields:
            if query in value:
                score += weight * 2
            elif value in query:
                score += weight
            else:
                for token in query.split():
                    if token in value:
                        score += weight * 0.5
        return score


vehicle_service = VehicleService()
