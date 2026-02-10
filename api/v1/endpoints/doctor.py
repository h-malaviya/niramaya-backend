from datetime import date, datetime, timedelta, timezone
import math
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query,status
from sqlalchemy import case, select, or_, and_, func, String
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import DEFAULT_PAGE, DEFAULT_PER_PAGE, MAX_PER_PAGE
from database.postgres import get_db
from dependencies.auth import get_current_user
from schemas.doctor_availability import AvailabilityRangeResponseDTO, AvailabilityResponseDTO, AvailabilityUpsertDTO, DaySlotsDTO, SlotDTO
from schemas.enum import AppointmentStatus
from schemas.schemas import Appointment, DoctorAvailability, StripePayment, User, DoctorProfile, DoctorCategory, DoctorCategoryMap, Role
from schemas.doctor_schema import DoctorListItemDTO, DoctorsListResponse
from typing import Optional, List
from sqlalchemy.orm import selectinload

from services.appointment_service import ensure_availability, generate_slots

router = APIRouter(prefix="/doctors", tags=["Doctors"])

@router.get("", response_model=DoctorsListResponse)
async def search_doctors(
    search: Optional[str] = Query(None, description="Search by name, about, qualification, category"),
    fees_max: Optional[float] = Query(None, ge=0),
    category: Optional[str] = Query(None),
    location: Optional[str] = Query(None, description="City or state"),
    gender: Optional[str] = Query(None),
    page: int = Query(DEFAULT_PAGE, ge=1),              
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
 
    filters = []

    if search:
        term = f"%{search.lower()}%"
        filters.append(
            or_(
                func.lower(User.first_name).like(term),
                func.lower(User.last_name).like(term),
                func.lower(DoctorProfile.about).like(term),
                func.cast(DoctorProfile.qualifications, String).ilike(term),
                func.lower(func.cast(DoctorCategory.name, String)).like(term),
            )
        )

    if fees_max is not None:
        filters.append(DoctorProfile.consultation_fee <= fees_max)

    if category:
        filters.append(
            func.lower(func.cast(DoctorCategory.name, String)) == category.lower()
        )

    if location:
        loc = f"%{location.lower()}%"
        filters.append(
            or_(
                func.lower(User.city).like(loc),
                func.lower(User.state).like(loc),
            )
        )

    if gender:
        filters.append(func.cast(User.gender, String) == gender.upper())

    # --------------------------------------------------
    # 2️⃣ BASE QUERY (ONLY IDs, FILTERED)
    # --------------------------------------------------
    base_stmt = (
        select(User.id)
        .join(DoctorProfile, DoctorProfile.user_id == User.id)
        .join(Role, Role.id == User.role_id)
        .outerjoin(DoctorCategoryMap, DoctorCategoryMap.doctor_id == DoctorProfile.id)
        .outerjoin(DoctorCategory, DoctorCategory.id == DoctorCategoryMap.category_id)
        .where(
            Role.name == "doctor",
            User.is_active.is_(True),
        )
    )

    if filters:
        base_stmt = base_stmt.where(and_(*filters))

    count_stmt = (
        select(func.count())
        .select_from(
            base_stmt.distinct(User.id).subquery()
        )
    )

    total = await db.scalar(count_stmt) or 0

    offset = (page - 1) * per_page

    doctor_ids_stmt = (
        base_stmt
        .distinct(User.id)
        .order_by(User.id)
        .offset(offset)
        .limit(per_page)
    )

    doctor_ids = [
        row[0] for row in (await db.execute(doctor_ids_stmt)).all()
    ]

    if not doctor_ids:
        return {
            "doctors": [],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_results": total,
                "total_pages": math.ceil(total / per_page) if total else 0,
            },
        }

    data_stmt = (
        select(User, DoctorProfile)
        .join(DoctorProfile, DoctorProfile.user_id == User.id)
        .join(Role, Role.id == User.role_id)
        .options(selectinload(DoctorProfile.categories))
        .where(
            User.id.in_(doctor_ids),
            Role.name == "doctor",
            User.is_active.is_(True),
        )
        # ✅ PRESERVE PAGINATION ORDER
        .order_by(
            case(
                {doctor_id: index for index, doctor_id in enumerate(doctor_ids)},
                value=User.id,
            )
        )
    )


    rows = (await db.execute(data_stmt)).all()

    # --------------------------------------------------
    # 6️⃣ BUILD RESPONSE (DEDUP SAFE)
    # --------------------------------------------------
    doctors_map = {}

    for user, profile in rows:
        if user.id not in doctors_map:
            doctors_map[user.id] = {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "gender": user.gender.value,
                "city": user.city,
                "state": user.state,
                 "qualifications": profile.qualifications,
                "profile_image_url": user.profile_image_url,
                "consultation_fee": float(profile.consultation_fee) if profile.consultation_fee else None,
                "experience_years": profile.experience_years,
                "about": profile.about,
                "categories": set()
            }

        if profile.categories:
            for cat in profile.categories:
                doctors_map[user.id]["categories"].add(cat.name.value)

    return{"doctors": [
        DoctorListItemDTO(
            **{
                **doc,
                "categories": list(doc["categories"])
            }
        )
        for doc in doctors_map.values()
    ],
    "pagination": {
        "page": page,
        "per_page": per_page,
        "total_results": total,
        "total_pages": math.ceil(total / per_page) if total else 0,
    },
    }

@router.get(
    "/{doctor_id}/slots",
    response_model=AvailabilityResponseDTO
    
)
async def get_doctor_slots(
    doctor_id: uuid.UUID,
    date: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    availability = await ensure_availability(db, doctor_id, date)

    if not availability or not availability.is_active:
        raise HTTPException(404, "Doctor not available")

    all_slots = generate_slots(
        availability.start_time,
        availability.end_time,
        availability.slot_duration,
        availability.break_start,
        availability.break_end
    )

    stmt = select(Appointment).where(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date == date,
        Appointment.status.in_([
            AppointmentStatus.HOLD,
            AppointmentStatus.PAYMENT_PENDING,
            AppointmentStatus.PAID,
            AppointmentStatus.COMPLETED
        ])
    )

    appointments = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc)

    slot_state_map = {}

    for appt in appointments:
        if appt.status in [AppointmentStatus.PAID, AppointmentStatus.COMPLETED]:
            slot_state_map[appt.start_time] = ("booked", None)

        elif appt.status in [AppointmentStatus.HOLD, AppointmentStatus.PAYMENT_PENDING]:
            if appt.lock_expires_at and appt.lock_expires_at > now:
                slot_state_map[appt.start_time] = ("hold", appt.lock_expires_at)

    slots = []
    for st, et in all_slots:
        state, expires = slot_state_map.get(st, ("available", None))
        slots.append(
            SlotDTO(
                start_time=st,
                end_time=et,
                state=state,
                hold_expires_at=expires
            )
        )

    return AvailabilityResponseDTO(
        doctor_id=str(doctor_id),
        available_date=date,
        start_time=availability.start_time,
        end_time=availability.end_time,
        break_start=availability.break_start,
        break_end=availability.break_end,
        slot_duration=availability.slot_duration,
        is_active=availability.is_active,
        slots=slots
    )

@router.post(
    "/availability",
    response_model=AvailabilityResponseDTO
)
async def upsert_availability(
    payload: AvailabilityUpsertDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != 'doctor':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only doctors can manage availability"
        )
    stmt = select(DoctorAvailability).where(
        DoctorAvailability.doctor_id == current_user.id,
        DoctorAvailability.available_date == payload.available_date
    )

    availability = (await db.execute(stmt)).scalar_one_or_none()

    if availability:
        for field, value in payload.model_dump().items():
            setattr(availability, field, value)
    else:
        availability = DoctorAvailability(
            doctor_id=current_user.id,
            **payload.model_dump()
        )
        db.add(availability)

    await db.commit()
    await db.refresh(availability)

    slots = generate_slots(
        availability.start_time,
        availability.end_time,
        availability.slot_duration,
        availability.break_start,
        availability.break_end
    )

    return AvailabilityResponseDTO(
        doctor_id=str(current_user.id),
        available_date=availability.available_date,
        start_time=availability.start_time,
        end_time=availability.end_time,
        break_start=availability.break_start,
        break_end=availability.break_end,
        slot_duration=availability.slot_duration,
        is_active=availability.is_active,
        slots=[
            SlotDTO(
                start_time=s,
                end_time=e,
                state="available",
                hold_expires_at=None
            )
            for s, e in slots
        ]
    )

@router.get(
    "/{doctor_id}/slots/range",
    response_model=AvailabilityRangeResponseDTO
)
async def get_doctor_slots_range(
    doctor_id: uuid.UUID,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    today = date.today()
    result_days = []

    for i in range(days):
        target_date = today + timedelta(days=i)
        if target_date.weekday() == 6:
            result_days.append(
                DaySlotsDTO(
                    available_date=target_date,
                    is_active=False,
                    start_time=None,
                    end_time=None,
                    break_start=None,
                    break_end=None,
                    slot_duration=None,
                    slots=[]
                )
            )
            continue
        availability = await ensure_availability(db, doctor_id, target_date)

        # Doctor off / inactive day
        if not availability or not availability.is_active:
            result_days.append(
                DaySlotsDTO(
                    available_date=target_date,
                    is_active=False,
                    start_time=None,
                    end_time=None,
                    break_start=None,
                    break_end=None,
                    slot_duration=None,
                    slots=[]
                )
            )
            continue

        all_slots = generate_slots(
            availability.start_time,
            availability.end_time,
            availability.slot_duration,
            availability.break_start,
            availability.break_end
        )

        stmt = select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == target_date,
            Appointment.status.in_([
                AppointmentStatus.HOLD,
                AppointmentStatus.PAYMENT_PENDING,
                AppointmentStatus.PAID,
                AppointmentStatus.COMPLETED
            ])
        )

        appointments = (await db.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)

        slot_state_map = {}

        for appt in appointments:
            if appt.status in [AppointmentStatus.PAID, AppointmentStatus.COMPLETED]:
                slot_state_map[appt.start_time] = ("booked", None)

            elif appt.status in [AppointmentStatus.HOLD, AppointmentStatus.PAYMENT_PENDING]:
                if appt.lock_expires_at and appt.lock_expires_at > now:
                    slot_state_map[appt.start_time] = ("hold", appt.lock_expires_at)

        slots = [
            SlotDTO(
                start_time=st,
                end_time=et,
                state=slot_state_map.get(st, ("available", None))[0],
                hold_expires_at=slot_state_map.get(st, ("available", None))[1]
            )
            for st, et in all_slots
        ]

        result_days.append(
            DaySlotsDTO(
                available_date=target_date,
                is_active=True,
                start_time=availability.start_time,
                end_time=availability.end_time,
                break_start=availability.break_start,
                break_end=availability.break_end,
                slot_duration=availability.slot_duration,
                slots=slots
            )
        )

    return AvailabilityRangeResponseDTO(
        doctor_id=str(doctor_id),
        days=result_days
    )

@router.get("/appointments/history")
async def get_doctor_appointment_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors allowed")

    q = (
        select(Appointment)
        .where(Appointment.doctor_id == current_user.id)
        .order_by(Appointment.appointment_date.desc(), Appointment.start_time.desc())
    )

    appts = (await db.execute(q)).scalars().all()

    results = []

    for a in appts:
        patient = (await db.execute(select(User).where(User.id == a.patient_id))).scalar_one_or_none()
        payment = None

        if a.payment_session_id:
            payment = (
                await db.execute(
                    select(StripePayment).where(StripePayment.appointment_id == a.id)
                )
            ).scalar_one_or_none()

        results.append({
            "appointment_id": str(a.id),
            "date": a.appointment_date,
            "start_time": a.start_time,
            "end_time": a.end_time,
            "status": a.status,
            "patient": {
                "id": str(patient.id) if patient else None,
                "name": f"{patient.first_name} {patient.last_name}" if patient else None,
                "email": patient.email if patient else None,
                "profile_image_url":patient.profile_image_url
            } if patient else None,
            "description": a.description,
            "report_urls": a.report_urls or [],
            "payment": {
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status
            } if payment else None,
            "created_at": a.created_at
        })

    return results  # always []

@router.get("/upcoming-appointments")
async def get_doctor_upcoming_appointments(
    status: str | None = Query(None, regex="^(pending|approved)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors allowed")

    q = select(Appointment).where(Appointment.doctor_id == current_user.id)

    # status filter
    if status == "pending":
        q = q.where(Appointment.status == AppointmentStatus.REQUESTED)
    elif status == "approved":
        q = q.where(Appointment.status == AppointmentStatus.PAID)

    # date filters
    if start_date:
        q = q.where(Appointment.appointment_date >= start_date)
    if end_date:
        q = q.where(Appointment.appointment_date <= end_date)

    q = q.order_by(Appointment.appointment_date, Appointment.start_time)

    appts = (await db.execute(q)).scalars().all()

    results = []

    for a in appts:
        patient = (await db.execute(
            select(User).where(User.id == a.patient_id)
        )).scalar_one()

        # search filter
        if search:
            s = search.lower()
            if not (
                s in (patient.first_name or "").lower()
                or s in (patient.last_name or "").lower()
                or s in (patient.city or "").lower()
                or s in (a.description or "").lower()
            ):
                continue

        results.append({
            "appointment_id": str(a.id),
            "date": a.appointment_date,
            "start_time": str(a.start_time),
            "end_time": str(a.end_time),
            "status": a.status.value,
            "patient": {
                "id": str(patient.id),
                "name": f"{patient.first_name} {patient.last_name}",
                "email": patient.email,
                "profile_image_url": patient.profile_image_url,
                "city": patient.city,
                "state": patient.state
            },
            "description": a.description,
            "report_urls": a.report_urls or []
        })

    return results

def resolve_date_range(range: str):
    today = date.today()

    if range == "today":
        return today, today

    if range == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        return start, today

    if range == "month":
        start = today.replace(day=1)
        return start, today

    if range == "year":
        start = today.replace(month=1, day=1)
        return start, today

    raise HTTPException(400, "Invalid range. Use today|week|month|year")

@router.get("/analytics/revenue")
async def doctor_revenue_analytics(
    range: str = "month",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403)

    start, end = resolve_date_range(range)

    q = (
        select(Appointment.appointment_date, StripePayment.amount)
        .join(StripePayment, StripePayment.appointment_id == Appointment.id)
        .where(
            Appointment.doctor_id == current_user.id,
            Appointment.status == AppointmentStatus.PAID,
            Appointment.appointment_date.between(start, end)
        )
    )

    rows = (await db.execute(q)).all()

    revenue_map = {}
    for d, amount in rows:
        key = str(d)
        revenue_map[key] = revenue_map.get(key, 0) + amount / 100

    labels = sorted(revenue_map.keys())
    data = [revenue_map[d] for d in labels]

    return {
        "labels": labels,
        "datasets": [{"label": f"Revenue ({range})", "data": data}]
    }

@router.get("/analytics/appointments-status")
async def doctor_status_breakdown(
    range: str = "month",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403)

    start, end = resolve_date_range(range)

    q = select(Appointment.status).where(
        Appointment.doctor_id == current_user.id,
        Appointment.appointment_date.between(start, end),
        Appointment.status.in_([
            AppointmentStatus.PAID,
            AppointmentStatus.CANCELLED_BY_DOCTOR,
            AppointmentStatus.EXPIRED,
            AppointmentStatus.COMPLETED
        ])
    )

    rows = (await db.execute(q)).scalars().all()

    status_map = {}
    for s in rows:
        status_map[s] = status_map.get(s, 0) + 1

    return {
        "labels": list(status_map.keys()),
        "datasets": [{"label": "Appointments", "data": list(status_map.values())}]
    }

@router.get("/analytics/customers")
async def doctor_customers_analytics(
    range: str = "month",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403)

    start, end = resolve_date_range(range)

    q = select(Appointment.patient_id).where(
        Appointment.doctor_id == current_user.id,
        Appointment.status.in_([AppointmentStatus.PAID, AppointmentStatus.COMPLETED]),
        Appointment.appointment_date.between(start, end)
    )

    rows = (await db.execute(q)).scalars().all()

    total_customers = len(rows)
    unique_customers = len(set(rows))

    return {
        "labels": ["Unique Patients", "Total Visits"],
        "datasets": [{
            "label": f"Customers ({range})",
            "data": [unique_customers, total_customers]
        }]
    }

@router.get("/analytics/peak-hours")
async def doctor_peak_hours(
    range: str = "month",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403)

    start, end = resolve_date_range(range)

    q = select(Appointment.start_time).where(
        Appointment.doctor_id == current_user.id,
        Appointment.status == AppointmentStatus.PAID,
        Appointment.appointment_date.between(start, end)
    )

    rows = (await db.execute(q)).scalars().all()

    hour_map = {}
    for t in rows:
        hour = t.strftime("%H:00") # type: ignore
        hour_map[hour] = hour_map.get(hour, 0) + 1

    labels = sorted(hour_map.keys())
    data = [hour_map[h] for h in labels]

    return {
        "labels": labels,
        "datasets": [{"label": f"Peak Hours ({range})", "data": data}]
    }

