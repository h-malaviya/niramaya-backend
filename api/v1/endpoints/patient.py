
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.postgres import get_db
from dependencies.auth import get_current_user
from schemas.enum import AppointmentStatus
from schemas.schemas import Appointment, StripePayment, User


router = APIRouter(prefix='/patients',tags=['Patient'])

@router.get("/pending-payments")
async def get_pending_payments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can view pending payments")

    now = datetime.now(timezone.utc)

    q = select(Appointment).where(
        Appointment.patient_id == current_user.id,
        Appointment.status == AppointmentStatus.PAYMENT_PENDING
    )

    appts = (await db.execute(q)).scalars().all()

    results = []

    for a in appts:
        # 🔁 Auto-expire inline
        if a.lock_expires_at and a.lock_expires_at < now:
            a.status = AppointmentStatus.EXPIRED
            continue

        doctor = (
            await db.execute(select(User).where(User.id == a.doctor_id))
        ).scalar_one()

        results.append({
            "appointment_id": str(a.id),
            "doctor_name": f"{doctor.first_name} {doctor.last_name}",
            "date": a.appointment_date,
            "start_time": a.start_time,
            "end_time": a.end_time,
            "expires_at": a.lock_expires_at
        })

    await db.commit()

    # ✅ Always return list (empty or filled)
    return results

@router.get("/upcoming-appointments")
async def get_patient_upcoming_appointments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients allowed")

    now = datetime.now(timezone.utc).date()

    q = select(Appointment).where(
        Appointment.patient_id == current_user.id,
        Appointment.appointment_date >= now,
        Appointment.status.in_([
            AppointmentStatus.PAID,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.PAYMENT_PENDING
        ])
    ).order_by(Appointment.appointment_date, Appointment.start_time)

    appts = (await db.execute(q)).scalars().all()

    results = []

    for a in appts:
        # auto-expire pending
        if a.status == AppointmentStatus.PAYMENT_PENDING and a.lock_expires_at and a.lock_expires_at < datetime.now(timezone.utc):
            a.status = AppointmentStatus.EXPIRED
            continue

        doctor = (await db.execute(select(User).where(User.id == a.doctor_id))).scalar_one()
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
            "doctor": {
                "id": str(doctor.id),
                "name": f"{doctor.first_name} {doctor.last_name}",
                "email": doctor.email,
                "profile_image_url": doctor.profile_image_url,
                "city": doctor.city,
                "state": doctor.state
            },
            "description": a.description,
            "report_urls": a.report_urls or [],
            "payment": {
                "amount": payment.amount if payment else None,
                "currency": payment.currency if payment else None,
                "status": payment.status if payment else None
            } if payment else None
        })

    await db.commit()
    return results

@router.get("/appointments/history")
async def get_patient_appointment_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients allowed")

    q = (
        select(Appointment)
        .where(Appointment.patient_id == current_user.id)
        .order_by(Appointment.appointment_date.desc(), Appointment.start_time.desc())
    )

    appts = (await db.execute(q)).scalars().all()

    results = []

    for a in appts:
        doctor = (await db.execute(select(User).where(User.id == a.doctor_id))).scalar_one_or_none()
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
            "doctor": {
                "id": str(doctor.id) if doctor else None,
                "name": f"{doctor.first_name} {doctor.last_name}" if doctor else None,
                "email": doctor.email if doctor else None,
                "profile_image_url":doctor.profile_image_url
            } if doctor else None,
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
