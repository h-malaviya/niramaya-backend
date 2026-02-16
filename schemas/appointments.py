from datetime import date, time
import uuid
from pydantic import BaseModel


class DirectBookDTO(BaseModel):
    doctor_id: uuid.UUID
    appointment_date: date
    start_time: time
    end_time: time
