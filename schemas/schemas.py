from sqlalchemy import (
    Index, String, Boolean, DateTime, Date, Time,
    ForeignKey, Integer, Enum as SQLEnum,
    Numeric, Text, JSON, UniqueConstraint, text
)
from sqlalchemy.orm import (
    declarative_base, relationship, Mapped, mapped_column
)
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone,date,time
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
    phone_number: Mapped[Optional[str]] = mapped_column(String(20))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(String(100))
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
    report_urls: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)

    status: Mapped[AppointmentStatus] = mapped_column(
        SQLEnum(AppointmentStatus, name="appointment_status_enum", native_enum=True),
        nullable=False
    )

    lock_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payment_session_id: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
         Index(
            "uq_doctor_slot_active",
            "doctor_id",
            "appointment_date",
            "start_time",
            unique=True,
            postgresql_where=text(
                "status IN ('HOLD', 'PAYMENT_PENDING', 'PAID', 'COMPLETED')"
            ),
        ),
    )

class StripePayment(Base):
    __tablename__ = "stripe_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE")
    )

    stripe_payment_session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
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

class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    token_hash: Mapped[str] = mapped_column(Text, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User")

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    token_hash: Mapped[str] = mapped_column(Text, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow
    )

    user: Mapped["User"] = relationship("User")

class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    available_date: Mapped[date] = mapped_column(Date, nullable=False)

    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    break_start: Mapped[Optional[time]] = mapped_column(Time)
    break_end: Mapped[Optional[time]] = mapped_column(Time)

    slot_duration: Mapped[int] = mapped_column(
        Integer,
        default=20,
        nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "doctor_id",
            "available_date",
            name="uq_doctor_availability_date"
        ),
    )

    doctor: Mapped["User"] = relationship("User")
