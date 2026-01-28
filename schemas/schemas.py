from sqlalchemy import (
    Column, String, Boolean, DateTime, Date, Time,
    ForeignKey, Integer, Enum, Numeric, Text, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime,timezone
import uuid
import enum

Base = declarative_base()

class RoleEnum(str, enum.Enum):
    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"


class AppointmentStatus(str, enum.Enum):
    HOLD = "HOLD"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_DOCTOR = "CANCELLED_BY_DOCTOR"
    EXPIRED = "EXPIRED"


class StripePaymentStatus(str, enum.Enum):
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class DoctorCategoryEnum(str, enum.Enum):
    FAMILY_PHYSICIAN = "Family Physician"
    PEDIATRICIAN = "Pediatrician"
    INTERNIST = "Internist"
    GERIATRICIAN = "Geriatrician"

    CARDIOLOGIST = "Cardiologist"
    DERMATOLOGIST = "Dermatologist"
    ENDOCRINOLOGIST = "Endocrinologist"
    GASTROENTEROLOGIST = "Gastroenterologist"
    NEUROLOGIST = "Neurologist"
    ONCOLOGIST = "Oncologist"
    OBSTETRICIAN_GYNECOLOGIST = "Obstetrician & Gynecologist"
    PSYCHIATRIST = "Psychiatrist"
    PULMONOLOGIST = "Pulmonologist"
    RHEUMATOLOGIST = "Rheumatologist"
    NEPHROLOGIST = "Nephrologist"
    ALLERGIST_IMMUNOLOGIST = "Allergist / Immunologist"

    GENERAL_SURGEON = "General Surgeon"
    ORTHOPEDIC_SURGEON = "Orthopedic Surgeon"
    NEUROSURGEON = "Neurosurgeon"
    OPHTHALMOLOGIST = "Ophthalmologist"
    ENT = "ENT (Otolaryngologist)"
    UROLOGIST = "Urologist"

class Role(Base):
    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Enum(RoleEnum), unique=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)

    first_name = Column(String(100))
    last_name = Column(String(100))
    profile_image_url = Column(Text)

    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc)
    )

    sessions = relationship("UserSession", back_populates="user")

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    refresh_token_hash = Column(Text, nullable=False)

    device_id = Column(String(255))
    device_name = Column(String(255))
    user_agent = Column(Text)

    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("user_id", "is_active", name="uq_active_session"),
    )

class DoctorCategory(Base):
    __tablename__ = "doctor_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Enum(DoctorCategoryEnum), unique=True, nullable=False)
    description = Column(Text)

class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True)

    qualifications = Column(JSON, nullable=False)
    experience_years = Column(Integer)
    consultation_fee = Column(Numeric(10, 2))
    about = Column(Text)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc)
    )

    user = relationship("User")
    categories = relationship(
        "DoctorCategory",
        secondary="doctor_category_map",
        backref="doctors"
    )

class DoctorCategoryMap(Base):
    __tablename__ = "doctor_category_map"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctor_profiles.id", ondelete="CASCADE"))
    category_id = Column(UUID(as_uuid=True), ForeignKey("doctor_categories.id", ondelete="CASCADE"))

    __table_args__ = (
        UniqueConstraint("doctor_id", "category_id", name="uq_doctor_category"),
    )

class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

class DoctorAvailability(Base):
    __tablename__ = "doctor_availability"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    available_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    break_start = Column(Time)
    break_end = Column(Time)

    slot_duration = Column(Integer, default=20)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("doctor_id", "available_date", name="uq_doctor_date"),
    )

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    patient_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    appointment_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    description = Column(Text)
    report_urls = Column(JSON)

    status = Column(Enum(AppointmentStatus), nullable=False)

    lock_expires_at = Column(DateTime(timezone=True))
    payment_intent_id = Column(String(255))

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE"))

    stripe_payment_intent_id = Column(String(255), unique=True, nullable=False)
    stripe_charge_id = Column(String(255))

    amount = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False)
    payment_method_type = Column(String(50))

    status = Column(Enum(StripePaymentStatus), nullable=False)
    receipt_url = Column(Text)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc)
    )

