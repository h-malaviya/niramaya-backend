import enum

class RoleEnum(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"

class GenderEnum(str,enum.Enum):
    MALE="male"
    FEMALE="female"

class AppointmentStatus(str, enum.Enum):
    HOLD = "hold"
    PAYMENT_PENDING = "payment_pending"
    PAID = "paid"
    COMPLETED = "completed"
    CANCELLED_BY_DOCTOR = "cancelled_by_doctor"
    EXPIRED = "expired"

class StripePaymentStatus(str, enum.Enum):
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class DoctorCategoryEnum(str, enum.Enum):
    FAMILY_PHYSICIAN = "family_physician"
    PEDIATRICIAN = "pediatrician"
    INTERNIST = "internist"
    GERIATRICIAN = "geriatrician"

    CARDIOLOGIST = "cardiologist"
    DERMATOLOGIST = "dermatologist"
    ENDOCRINOLOGIST = "endocrinologist"
    GASTROENTEROLOGIST = "gastroenterologist"
    NEUROLOGIST = "neurologist"
    ONCOLOGIST = "oncologist"
    OBSTETRICIAN_GYNECOLOGIST = "obstetrician_gynecologist"
    PSYCHIATRIST = "psychiatrist"
    PULMONOLOGIST = "pulmonologist"
    RHEUMATOLOGIST = "rheumatologist"
    NEPHROLOGIST = "nephrologist"
    ALLERGIST_IMMUNOLOGIST = "allergist_immunologist"

    GENERAL_SURGEON = "general_surgeon"
    ORTHOPEDIC_SURGEON = "orthopedic_surgeon"
    NEUROSURGEON = "neurosurgeon"
    OPHTHALMOLOGIST = "ophthalmologist"
    ENT = "ent"
    UROLOGIST = "urologist"
