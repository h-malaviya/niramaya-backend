from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID

class DoctorListItemDTO(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    gender: str
    city: Optional[str]
    state: Optional[str]
    profile_image_url: Optional[str]
    consultation_fee: Optional[float]
    experience_years: Optional[int]
    about: Optional[str]
    categories: List[str]
    qualifications: List[str]

class DoctorsListResponse(BaseModel):
    doctors: list[DoctorListItemDTO]
    pagination: dict
