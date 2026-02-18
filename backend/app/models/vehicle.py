from pydantic import BaseModel


class Vehicle(BaseModel):
    id: str
    make: str
    model: str
    year: int
    trim: str = ""
    photo_url: str = ""
    manual_available: bool = False


class VehicleMatch(BaseModel):
    vehicle: Vehicle
    score: float
