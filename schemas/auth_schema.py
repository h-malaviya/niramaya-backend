from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date

from schemas.enum import RoleEnum,GenderEnum,DoctorCategoryEnum

class UserBase(BaseModel):
    email: EmailStr

class UserLogin(UserBase):
    email:EmailStr
    password: str
    device_id: Optional[str] = "unknown"

class UserSignup(UserBase):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    date_of_birth: date
    gender: GenderEnum
    role: RoleEnum

class DoctorSignup(BaseModel):
    qualifications: list[str]
    experience_years: int
    category_names: list[DoctorCategoryEnum]
 
class Token(BaseModel):
    access_token: str
    refresh_token: str