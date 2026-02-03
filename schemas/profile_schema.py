from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import date
from schemas.enum import DoctorCategoryEnum
from schemas.schemas import DoctorProfile
class BaseProfileDTO(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    city: Optional[str]
    state: Optional[str]
    address: Optional[str]
    country: Optional[str]
    profile_image_url: Optional[str]

    class Config:
        from_attributes = True


class UserProfileResponse(BaseProfileDTO):
    id: UUID
    email: str
    gender: str
    date_of_birth: date
    is_verified: bool
    is_active: bool


class BaseProfileUpdate(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    city: Optional[str]
    state: Optional[str]
    address: Optional[str]
    country: Optional[str]
    profile_image_url: Optional[str]

    class Config:
        from_attributes = True


class DoctorProfileBase(BaseModel):
    qualifications: Optional[List[str]]
    experience_years: Optional[int]
    consultation_fee: Optional[float]
    about: Optional[str]


    class Config:
        from_attributes = True

    
class ProfileUpdateRequest(BaseModel):
    user: Optional[BaseProfileDTO] = None
    doctor: Optional[DoctorProfileBase] = None

class DoctorProfileResponse(DoctorProfileBase):
    pass


class ProfileResponse(BaseModel):
    user: UserProfileResponse
    doctor_profile: Optional[DoctorProfileResponse] = None
