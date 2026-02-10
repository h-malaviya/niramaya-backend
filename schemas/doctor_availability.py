from pydantic import BaseModel, Field
from datetime import date, time,datetime
from typing import Optional, List,Literal
import uuid
SlotState = Literal["available", "hold", "booked"]

class AvailabilityUpsertDTO(BaseModel):
    available_date: date
    start_time: time
    end_time: time
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    slot_duration: int = Field(default=20, ge=5, le=120)
    is_active: bool = True

class SlotDTO(BaseModel):
    start_time: time
    end_time: time
    state: SlotState
    hold_expires_at: Optional[datetime] = None

class AvailabilityResponseDTO(BaseModel):
    doctor_id: str
    available_date: date
    start_time: time
    end_time: time
    break_start: Optional[time]
    break_end: Optional[time]
    slot_duration: int
    is_active: bool
    slots: List[SlotDTO]

class HoldAppointmentDTO(BaseModel):
    doctor_id: uuid.UUID
    appointment_date: date
    start_time: time
    end_time: time
    description: Optional[str] = None

class DaySlotsDTO(BaseModel):
    available_date: date
    is_active: bool
    start_time: time | None
    end_time: time | None
    break_start: time | None
    break_end: time | None
    slot_duration: int | None
    slots: list[SlotDTO]


class AvailabilityRangeResponseDTO(BaseModel):
    doctor_id: str
    days: list[DaySlotsDTO]