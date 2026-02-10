from datetime import date, datetime, time, timedelta
import uuid
from typing import List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.schemas import DoctorAvailability

DEFAULT_START = time(10, 0)
DEFAULT_END = time(17, 0)
DEFAULT_BREAK_START = time(13, 0)
DEFAULT_BREAK_END = time(14, 0)
DEFAULT_SLOT_DURATION = 20

async def ensure_availability(
    db: AsyncSession,
    doctor_id: uuid.UUID,
    target_date: date
) -> DoctorAvailability | None:

    today = date.today()

    if target_date < today - timedelta(days=1) or target_date > today + timedelta(days=30):
        return None

    # Sunday off
    if target_date.weekday() == 6:
        return None

    stmt = select(DoctorAvailability).where(
        DoctorAvailability.doctor_id == doctor_id,
        DoctorAvailability.available_date == target_date
    )
    availability = (await db.execute(stmt)).scalar_one_or_none()

    if availability:
        return availability

    availability = DoctorAvailability(
        doctor_id=doctor_id,
        available_date=target_date,
        start_time=DEFAULT_START,
        end_time=DEFAULT_END,
        break_start=DEFAULT_BREAK_START,
        break_end=DEFAULT_BREAK_END,
        slot_duration=DEFAULT_SLOT_DURATION,
        is_active=True
    )

    db.add(availability)
    await db.commit()
    await db.refresh(availability)

    return availability

def generate_slots(
    start_time: time,
    end_time: time,
    slot_duration: int,
    break_start: time | None,
    break_end: time | None
) -> List[Tuple[time, time]]:

    slots = []
    cursor = datetime.combine(date.min, start_time)
    end_dt = datetime.combine(date.min, end_time)

    while cursor + timedelta(minutes=slot_duration) <= end_dt:
        st = cursor.time()
        et = (cursor + timedelta(minutes=slot_duration)).time()

        if break_start and break_end:
            if break_start <= st < break_end:
                cursor += timedelta(minutes=slot_duration)
                continue

        slots.append((st, et))
        cursor += timedelta(minutes=slot_duration)

    return slots

