from sqlalchemy import (
    String, Boolean, DateTime, Date, Time,
    ForeignKey, Integer, Enum as SQLEnum,
    Numeric, Text, JSON, UniqueConstraint
)
from sqlalchemy.orm import (
    declarative_base, relationship, Mapped, mapped_column
)
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from schemas.enum import (
    GenderEnum,
    DoctorCategoryEnum,
    RoleEnum,
    AppointmentStatus,
    StripePaymentStatus
)

Base = declarative_base()
utcnow = lambda: datetime.now(timezone.utc)

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[RoleEnum] = mapped_column(
        SQLEnum(RoleEnum, name="role_enum", native_enum=True),
        unique=True,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))

    gender: Mapped[GenderEnum] = mapped_column(
        SQLEnum(GenderEnum, name="gender_enum", native_enum=True),
        nullable=False
    )

    profile_image_url: Mapped[Optional[str]] = mapped_column(Text)
    date_of_birth: Mapped[Date] = mapped_column(Date, nullable=False)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id"),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow
    )

    sessions: Mapped[List["UserSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )

class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE")
    )

    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)

    device_id: Mapped[Optional[str]] = mapped_column(String(255))
    device_name: Mapped[Optional[str]] = mapped_column(String(255))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="sessions")

class DoctorCategory(Base):
    __tablename__ = "doctor_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[DoctorCategoryEnum] = mapped_column(
        SQLEnum(
            DoctorCategoryEnum,
            name="doctor_category_enum",
            native_enum=True
        ),
        unique=True,
        nullable=False
    )

    description: Mapped[Optional[str]] = mapped_column(Text)

class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True
    )

    qualifications: Mapped[dict] = mapped_column(JSON, nullable=False)
    experience_years: Mapped[Optional[int]] = mapped_column(Integer)
    consultation_fee: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    about: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship()
    categories: Mapped[List["DoctorCategory"]] = relationship(
        secondary="doctor_category_map",
        backref="doctors"
    )

class DoctorCategoryMap(Base):
    __tablename__ = "doctor_category_map"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctor_profiles.id", ondelete="CASCADE")
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctor_categories.id", ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint("doctor_id", "category_id", name="uq_doctor_category"),
    )

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    appointment_date: Mapped[Date] = mapped_column(Date, nullable=False)
    start_time: Mapped[Time] = mapped_column(Time, nullable=False)
    end_time: Mapped[Time] = mapped_column(Time, nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text)
    report_urls: Mapped[Optional[dict]] = mapped_column(JSON)

    status: Mapped[AppointmentStatus] = mapped_column(
        SQLEnum(AppointmentStatus, name="appointment_status_enum", native_enum=True),
        nullable=False
    )

    lock_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "doctor_id",
            "appointment_date",
            "start_time",
            name="uq_doctor_slot"
        ),
    )

class StripePayment(Base):
    __tablename__ = "stripe_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE")
    )

    stripe_payment_intent_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    stripe_charge_id: Mapped[Optional[str]] = mapped_column(String(255))

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_method_type: Mapped[Optional[str]] = mapped_column(String(50))

    status: Mapped[StripePaymentStatus] = mapped_column(
        SQLEnum(StripePaymentStatus, name="stripe_payment_status_enum", native_enum=True),
        nullable=False
    )

    receipt_url: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
