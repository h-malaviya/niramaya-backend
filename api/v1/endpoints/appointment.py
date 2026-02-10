from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile,status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from datetime import datetime, timedelta, timezone,date
import uuid
from core.config import FRONTEND_URL
from core.mail import send_email
from database.postgres import get_db
from dependencies.auth import get_current_user
from schemas.enum import StripePaymentStatus
from schemas.profile_schema import HoldAppointmentForm
from schemas.schemas import Appointment, AppointmentStatus, DoctorProfile, StripePayment, User
from services.appointment_service import ensure_availability,generate_slots
from services.file_upload_service import upload_image, upload_pdf
from core.stripe_client import stripe
from loguru import logger
router = APIRouter(
    prefix='/appointments',
    tags=["appointments"]
    )

@router.post("/hold")
async def hold_appointment(
    form: HoldAppointmentForm = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "patient":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can book appointments"
        )

    today = date.today()
    if form.appointment_date < today:
        raise HTTPException(400, "Cannot book appointment for past dates")

    availability = await ensure_availability(db, form.doctor_id, form.appointment_date)
    if availability is None:
        raise HTTPException(400, "Booking allowed only for next 30 days and working days")

    if not availability.is_active:
        raise HTTPException(400, "Doctor not available on this date")

    valid_slots = generate_slots(
        availability.start_time,
        availability.end_time,
        availability.slot_duration,
        availability.break_start,
        availability.break_end
    )

    if (form.start_time, form.end_time) not in valid_slots:
        raise HTTPException(400, "Invalid slot selected")

    stmt = select(Appointment).where(
        Appointment.doctor_id == form.doctor_id,
        Appointment.appointment_date == form.appointment_date,
        Appointment.start_time == form.start_time,
        Appointment.status.in_([
            AppointmentStatus.HOLD,
            AppointmentStatus.PAYMENT_PENDING,
            AppointmentStatus.REQUESTED,
            AppointmentStatus.PAID,
            AppointmentStatus.COMPLETED
        ])
    )

    existing = (await db.execute(stmt)).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if existing:
        if existing.status in [AppointmentStatus.PAID, AppointmentStatus.COMPLETED]:
            raise HTTPException(409, "Slot already booked")

        if existing.lock_expires_at and existing.lock_expires_at > now:
            raise HTTPException(409, "Slot temporarily held by another user")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    appointment = Appointment(
        patient_id=current_user.id,
        doctor_id=form.doctor_id,
        appointment_date=form.appointment_date,
        start_time=form.start_time,
        end_time=form.end_time,
        status=AppointmentStatus.HOLD,
        lock_expires_at=expires_at
    )

    try:
        db.add(appointment)
        await db.commit()
        await db.refresh(appointment)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Slot already held or booked")

    return {
        "appointment_id": str(appointment.id),
        "status": appointment.status,
        "lock_expires_at": appointment.lock_expires_at
    }

@router.post("/{appointment_id}/request-booking")
async def request_booking(
    appointment_id: uuid.UUID,
    description: str = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "patient":
        raise HTTPException(403, "Only patients can book appointments")

    appt = (await db.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )).scalar_one_or_none()

    if not appt or appt.patient_id != current_user.id:
        raise HTTPException(404, "Appointment not found")

    if appt.status != AppointmentStatus.HOLD:
        raise HTTPException(400, "Appointment not in HOLD state")

    now = datetime.now(timezone.utc)
    if not appt.lock_expires_at or appt.lock_expires_at < now:
        appt.status = AppointmentStatus.EXPIRED
        await db.commit()
        raise HTTPException(400, "Hold expired")

    # Upload reports now (not at HOLD)
    report_urls = []
    if files:
        for file in files:
            uploaded = await upload_pdf(file.file, "reports") if file.content_type == "application/pdf" else await upload_image(file.file, "reports")
            report_urls.append(uploaded["url"])

    appt.description = description
    appt.report_urls = report_urls
    appt.status = AppointmentStatus.REQUESTED  
    appt.lock_expires_at = now + timedelta(hours=12)

    await db.commit()

    doctor = (await db.execute(select(User).where(User.id == appt.doctor_id))).scalar_one()

    send_email(
        to_email=doctor.email,
        subject="New Appointment Request",
        html=f"""
        <p>Patient: {current_user.first_name} {current_user.last_name}</p>
        <p>Date: {appt.appointment_date}</p>
        <p>Time: {appt.start_time} - {appt.end_time}</p>
        <p>Description: {description}</p>
        <p>
          <a href="{FRONTEND_URL}/doctor/appointments/{appt.id}/accept">Accept</a> |
          <a href="{FRONTEND_URL}/doctor/appointments/{appt.id}/reject">Reject</a>
        </p>
        """
    )

    return {"message": "Booking request sent to doctor"}

@router.post("/{appointment_id}/reject")
async def doctor_reject(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403)

    stmt = select(Appointment).where(Appointment.id == appointment_id)
    appointment = (await db.execute(stmt)).scalar_one_or_none()

    if not appointment or appointment.doctor_id != current_user.id:
        raise HTTPException(404)

    appointment.status = AppointmentStatus.CANCELLED_BY_DOCTOR
    await db.commit()

    patient = (
        await db.execute(
            select(User).where(User.id == appointment.patient_id)
        )
    ).scalar_one_or_none()

    if not patient:
        raise HTTPException(500, "Patient user not found")

    send_email(
        to_email=patient.email,
        subject="Appointment Rejected",
        html="<p>Doctor rejected your appointment request.</p>"
    )

@router.post("/{appointment_id}/accept")
async def doctor_accept(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(403, "Only doctors can accept appointments")

    appointment = (
        await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
    ).scalar_one_or_none()

    if not appointment or appointment.doctor_id != current_user.id:
        raise HTTPException(404, "Appointment not found")
    
    if appointment.status == AppointmentStatus.PAYMENT_PENDING:
        raise HTTPException(409, "Payment already initiated")

    if appointment.status != AppointmentStatus.REQUESTED:
        raise HTTPException(400, "Invalid appointment state")

    now = datetime.now(timezone.utc)
    if appointment.lock_expires_at and appointment.lock_expires_at < now:
        appointment.status = AppointmentStatus.CANCELLED_BY_DOCTOR
        await db.commit()
        raise HTTPException(400, "Booking request expired")

    doctor_profile = (
        await db.execute(
            select(DoctorProfile).where(DoctorProfile.user_id == current_user.id)
        )
    ).scalar_one_or_none()

    if not doctor_profile or not doctor_profile.consultation_fee:
        raise HTTPException(400, "Doctor fee not set")

    patient = (
        await db.execute(
            select(User).where(User.id == appointment.patient_id)
        )
    ).scalar_one_or_none()

    if not patient:
        raise HTTPException(500, "Patient user not found")

    amount_paise = int(float(doctor_profile.consultation_fee) * 100)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            customer_email=current_user.email,
            customer_creation="always",

            billing_address_collection="required",  

    
            line_items=[{
                "price_data": {
                    "currency": "inr",
                    "unit_amount": int(doctor_profile.consultation_fee * 100),
                    "product_data": {
                        "name": "Doctor Consultation Fee",
                        "description": f"{current_user.first_name} {current_user.last_name} consultation"
                    },
                },
                "quantity": 1,
            }],
            metadata={"appointment_id": str(appointment_id)},
            success_url=f"{FRONTEND_URL}/payment/success/{appointment_id}",
            cancel_url=f"{FRONTEND_URL}/payment/failure/{appointment_id}",
        )
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {str(e)}")

    stripe_payment = StripePayment(
        appointment_id=appointment.id,
        stripe_payment_session_id=session.id,
        amount=amount_paise,
        currency="inr",
        status=StripePaymentStatus.REQUIRES_PAYMENT_METHOD
    )

    appointment.status = AppointmentStatus.PAYMENT_PENDING
    appointment.payment_session_id = session.id
    appointment.lock_expires_at = now + timedelta(minutes=15)

    db.add(stripe_payment)
    await db.commit()

    payment_url = f"{FRONTEND_URL}/patient/payment?appointment_id={appointment.id}"

    send_email(
        to_email=patient.email,
        subject="Complete Payment for Appointment",
        html=f"""
        <p>Your appointment is approved.</p>
        <p><a href="{payment_url}">Pay Now</a></p>
        <p>Expires in 15 minutes.</p>
        """
    )


    return {
        "payment_session_id": session.id,
        "expires_at": appointment.lock_expires_at,
        "amount": amount_paise,
        "currency": "inr",
        "checkout_url": session.url
    }

@router.post("/{appointment_id}/confirm-payment")
async def confirm_payment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()

    if not appt or appt.patient_id != current_user.id:
        raise HTTPException(404, "Appointment not found")

    if appt.status != AppointmentStatus.PAYMENT_PENDING:
        raise HTTPException(400, "Invalid appointment state")

    if not appt.payment_session_id:
        raise HTTPException(404, "Payment session not found")
    now = datetime.now(timezone.utc)

    if appt.lock_expires_at and appt.lock_expires_at < now:
        appt.status = AppointmentStatus.EXPIRED
        await db.commit()
        raise HTTPException(400, "Payment window expired")
    
    session = stripe.checkout.Session.retrieve(appt.payment_session_id)

    logger.debug(f"session : {session}")
    payment = (
        await db.execute(
            select(StripePayment).where(
                StripePayment.stripe_payment_session_id == session.id
            )
        )
    ).scalar_one()

    if session.payment_status != "paid":
        appt.status = AppointmentStatus.EXPIRED
        payment.status = StripePaymentStatus.FAILED
        await db.commit()
        raise HTTPException(400, "Payment failed")

    if session.payment_status == "paid":
        appt.status = AppointmentStatus.PAID
        payment.status = StripePaymentStatus.SUCCEEDED
        payment.payment_method_type = session.payment_method_types[0]

        await db.commit()

        # Fetch doctor + patient emails
        patient = (await db.execute(select(User).where(User.id == appt.patient_id))).scalar_one()
        doctor = (await db.execute(select(User).where(User.id == appt.doctor_id))).scalar_one()

        send_email(patient.email, "Appointment Confirmed", "Your payment is successful.")
        send_email(doctor.email, "New Appointment Confirmed", "Patient completed payment.")

        return {"status": "PAID"}

    raise HTTPException(400, "Payment not completed")

@router.post("/{appointment_id}/cancel-payment")
async def cancel_payment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()

    if not appt or appt.patient_id != current_user.id:
        raise HTTPException(404, "Appointment not found")

  
    now = datetime.now(timezone.utc)

    if appt.status == AppointmentStatus.PAID:
        raise HTTPException(400, "Payment already completed")

    if appt.lock_expires_at and appt.lock_expires_at < now:
        appt.status = AppointmentStatus.EXPIRED
        await db.commit()
        raise HTTPException(400, "Payment window expired")

    appt.status = AppointmentStatus.EXPIRED
    await db.commit()

    patient = (await db.execute(select(User).where(User.id == appt.patient_id))).scalar_one()

    send_email(patient.email, "Payment Cancelled", "Your appointment booking was cancelled.")

    return {"status": "CANCELLED"}

@router.get("/{appointment_id}/payment-info")
async def get_payment_info(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()

    if not appt or appt.patient_id != current_user.id:
        raise HTTPException(404, "Appointment not found")

    if appt.status != AppointmentStatus.PAYMENT_PENDING:
        raise HTTPException(400, "Payment not pending")
    now = datetime.now(timezone.utc)

    if appt.lock_expires_at and appt.lock_expires_at < now:
        appt.status = AppointmentStatus.EXPIRED
        await db.commit()
        raise HTTPException(400, "Payment window expired")

    payment = (
        await db.execute(
            select(StripePayment).where(
                StripePayment.stripe_payment_session_id == appt.payment_session_id
            )
        )
    ).scalar_one()

    return {
        "appointment_id": str(appt.id),
        "amount": payment.amount,
        "currency": payment.currency,
        "expires_at": appt.lock_expires_at,
        "client_secret": payment.stripe_payment_session_id  
    }

@router.get("/{appointment_id}/payment-link")
async def get_payment_link(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    appt = (
        await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    ).scalar_one_or_none()

    if not appt or appt.patient_id != current_user.id:
        raise HTTPException(404, "Appointment not found")

    if appt.status != AppointmentStatus.PAYMENT_PENDING:
        raise HTTPException(400, "No pending payment")

    if not appt.lock_expires_at or appt.lock_expires_at < datetime.now(timezone.utc):
        appt.status = AppointmentStatus.EXPIRED
        await db.commit()
        raise HTTPException(400, "Payment session expired")
    if not appt.payment_session_id:
        raise HTTPException(
            status_code=400,
            detail="Payment session not initialized"
        )
    session = stripe.checkout.Session.retrieve(appt.payment_session_id)

    return {
        "checkout_url": session.url,
        "expires_at": appt.lock_expires_at
    }

@router.get("/patient/pending-payments")
async def get_pending_payments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = select(Appointment).where(
        Appointment.patient_id == current_user.id,
        Appointment.status == AppointmentStatus.PAYMENT_PENDING
    )

    appts = (await db.execute(q)).scalars().all()

    results = []

    for a in appts:
        doctor = (await db.execute(select(User).where(User.id == a.doctor_id))).scalar_one()
        results.append({
            "appointment_id": str(a.id),
            "doctor_name": f"{doctor.first_name} {doctor.last_name}",
            "date": a.appointment_date,
            "start_time": a.start_time,
            "end_time": a.end_time,
            "expires_at": a.lock_expires_at
        })

    return results

