"""
chat_tools.py
─────────────
LangChain @tool wrappers that delegate DIRECTLY to your existing
route handler functions — zero logic duplication.

Pattern
───────
  Each tool:
    1. Pulls db + current_user from context vars (set per-request in chat.py)
    2. Calls the existing handler function with those args (bypasses FastAPI Depends)
    3. Serialises the result to a plain dict for the LLM

Existing handlers reused
─────────────────────────
  routers/doctor.py     → search_doctors, get_doctor_slots, get_doctor_slots_range
  routers/appointment.py→ direct_book_appointment
  routers/profile.py    → get_my_profile, update_profile
"""

from __future__ import annotations

import contextvars
import re
import uuid
from datetime import date, time, timedelta
from typing import Optional

from fastapi import HTTPException
from langchain_core.tools import tool
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.appointments import DirectBookDTO
from schemas.profile_schema import BaseProfileDTO, ProfileUpdateRequest
from schemas.schemas import User


# ─────────────────────────────────────────────────────────────────────────────
# Context vars – injected once per request from the chat router
# ─────────────────────────────────────────────────────────────────────────────

_db_ctx: contextvars.ContextVar[AsyncSession] = contextvars.ContextVar("_db_ctx")
_user_ctx: contextvars.ContextVar[User] = contextvars.ContextVar("_user_ctx")


def set_tool_context(db: AsyncSession, user: User) -> None:
    """Call this at the top of the /chat/message handler before graph runs."""
    _db_ctx.set(db)
    _user_ctx.set(user)


def _db() -> AsyncSession:
    return _db_ctx.get()


def _user() -> User:
    return _user_ctx.get()


# ─────────────────────────────────────────────────────────────────────────────
# Helper – flatten HTTPException into a dict the LLM can read
# ─────────────────────────────────────────────────────────────────────────────

def _http_err(e: HTTPException) -> dict:
    return {"error": e.detail, "status_code": e.status_code}


# ─────────────────────────────────────────────────────────────────────────────
# 0. RESOLVE APPOINTMENT DATE (pure python; deterministic)
# ─────────────────────────────────────────────────────────────────────────────

_WEEKDAY_TO_INT = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _next_weekday(from_date: date, weekday: int) -> date:
    """Return the next occurrence of weekday strictly after from_date."""
    delta = (weekday - from_date.weekday()) % 7
    if delta == 0:
        delta = 7
    return from_date + timedelta(days=delta)


@tool
async def resolve_appointment_date(text: str, today: Optional[str] = None) -> dict:
    """
    Deterministically resolve a relative date expression into an ISO date.

    Supports:
    - "tomorrow", "tmrw", "day after tomorrow"
    - "next monday" / "upcoming tuesday" / "this wednesday" / "coming thursday" / "on friday"
    - bare weekday names like "monday" (treated as the next occurrence)
    - ISO date "YYYY-MM-DD" passthrough

    Args:
      text: user-provided date text (e.g., "next monday")
      today: optional ISO date "YYYY-MM-DD" used as the reference. If omitted,
             server local date.today() is used.

    Returns:
      { ok: true, appointment_date: "YYYY-MM-DD", day_of_week: "Monday" }
      or { ok: false, error: "...", expected: "..." }
    """
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "error": "Empty date text", "expected": "e.g. tomorrow | next monday | 2026-02-24"}

    # Reference date
    try:
        ref = date.fromisoformat(today) if today else date.today()
    except Exception:
        ref = date.today()

    s = raw.lower().strip()
    s = re.sub(r"\s+", " ", s)

    # ISO date passthrough
    try:
        d = date.fromisoformat(s)
        return {"ok": True, "appointment_date": d.isoformat(), "day_of_week": d.strftime("%A")}
    except Exception:
        pass

    if s in ("tomorrow", "tmrw", "tmr"):
        d = ref + timedelta(days=1)
        return {"ok": True, "appointment_date": d.isoformat(), "day_of_week": d.strftime("%A")}

    if s in ("day after tomorrow", "day after tmrw", "day after tmr"):
        d = ref + timedelta(days=2)
        return {"ok": True, "appointment_date": d.isoformat(), "day_of_week": d.strftime("%A")}

    # Prefixes that all mean "the next occurrence of <weekday>"
    # Covers: "next monday", "upcoming tuesday", "this wednesday",
    #         "coming thursday", "following friday", "on monday", "on next monday"
    _NEXT_PREFIXES = ("on next ", "next ", "upcoming ", "this ", "coming ", "following ", "on ")
    for prefix in _NEXT_PREFIXES:
        if s.startswith(prefix):
            wd = s[len(prefix):].strip()
            if wd in _WEEKDAY_TO_INT:
                d = _next_weekday(ref, _WEEKDAY_TO_INT[wd])
                return {"ok": True, "appointment_date": d.isoformat(), "day_of_week": d.strftime("%A")}

    # bare weekday name -> next occurrence (even if today is that weekday)
    if s in _WEEKDAY_TO_INT:
        d = _next_weekday(ref, _WEEKDAY_TO_INT[s])
        return {"ok": True, "appointment_date": d.isoformat(), "day_of_week": d.strftime("%A")}

    return {
        "ok": False,
        "error": f"Could not parse date expression: {raw!r}",
        "expected": "tomorrow | next monday | upcoming tuesday | this friday | monday | YYYY-MM-DD",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. SEARCH DOCTORS  →  routers/doctor.py :: search_doctors()
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def search_doctors(
    search: Optional[str] = None,
    category: Optional[str] = None,
    location: Optional[str] = None,
    fees_max: Optional[float] = None,
    gender: Optional[str] = None,
    page: int = 1,
    per_page: int = 5,
) -> dict:
    """
    Search for doctors by name, specialty/category, location, gender or max consultation fee.
    Use this when the user mentions a health problem, doctor name, specialty, or location.
    Returns a list of matching doctors with id, name, categories, fee, experience, city.

    category values: family_physician, pediatrician, internist, cardiologist,
    dermatologist, endocrinologist, gastroenterologist, neurologist, oncologist,
    obstetrician_gynecologist, psychiatrist, pulmonologist, rheumatologist,
    nephrologist, allergist_immunologist, general_surgeon, orthopedic_surgeon,
    neurosurgeon, ophthalmologist, ent, urologist, geriatrician
    """
    # Import here to avoid circular imports at module level
    from api.v1.endpoints.doctor import search_doctors as _handler

    try:
        result = await _handler(
            search=search,
            fees_max=fees_max,
            category=category,
            location=location,
            gender=gender,
            page=page,
            per_page=per_page,
            db=_db(),
            current_user=_user(),
        )
        # Human-readable labels for category slugs
        _CATEGORY_LABELS = {
            "family_physician": "Family Physician",
            "pediatrician": "Pediatrician",
            "internist": "Internal Medicine",
            "geriatrician": "Geriatrician",
            "cardiologist": "Cardiologist (Heart)",
            "dermatologist": "Dermatologist (Skin)",
            "endocrinologist": "Endocrinologist (Hormones/Diabetes)",
            "gastroenterologist": "Gastroenterologist (Digestive)",
            "neurologist": "Neurologist (Brain/Nerves)",
            "oncologist": "Oncologist (Cancer)",
            "obstetrician_gynecologist": "Obstetrician & Gynecologist",
            "psychiatrist": "Psychiatrist (Mental Health)",
            "pulmonologist": "Pulmonologist (Lungs)",
            "rheumatologist": "Rheumatologist (Joints/Autoimmune)",
            "nephrologist": "Nephrologist (Kidneys)",
            "allergist_immunologist": "Allergist / Immunologist",
            "general_surgeon": "General Surgeon",
            "orthopedic_surgeon": "Orthopedic Surgeon (Bones/Joints)",
            "neurosurgeon": "Neurosurgeon",
            "ophthalmologist": "Ophthalmologist (Eyes)",
            "ent": "ENT (Ear, Nose & Throat)",
            "urologist": "Urologist",
        }

        def _readable_specialties(categories) -> str:
            if not categories:
                return "General Practice"
            labels = [_CATEGORY_LABELS.get(c, c.replace("_", " ").title()) for c in categories]
            return ", ".join(label for label in labels if label is not None)

        # result is a dict with "doctors" and "pagination" keys
        # Slim down doctor objects – LLM doesn't need every field
        slim_doctors = [
            {
                "id": str(d.id),
                "name": f"Dr. {d.first_name} {d.last_name}",
                "specialties": _readable_specialties(d.categories),
                "categories": d.categories,
                "city": d.city,
                "state": d.state,
                "consultation_fee": d.consultation_fee,
                "experience_years": d.experience_years,
            }
            for d in result["doctors"]
        ]
        return {
            "doctors": slim_doctors,
            "total": result["pagination"]["total_results"],
        }
    except HTTPException as e:
        return _http_err(e)
    except Exception as e:
        logger.error(f"search_doctors tool error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 2. GET SLOTS FOR A DATE  →  routers/doctor.py :: get_doctor_slots()
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def get_doctor_slots_for_date(
    doctor_id: str,
    appointment_date: str,
) -> dict:
    """
    Get all time slots for a doctor on a specific date (YYYY-MM-DD).
    Returns each slot with start_time, end_time, and state (available/hold/booked).
    Use this when the user has picked a doctor and wants to see open times on a date.
    """
    from api.v1.endpoints.doctor import get_doctor_slots as _handler

    try:
        result = await _handler(
            doctor_id=uuid.UUID(doctor_id),
            date=date.fromisoformat(appointment_date),
            db=_db(),
            current_user=_user(),
        )
        def _time_period(hour: int) -> str:
            if hour < 12:
                return "morning"
            elif hour < 17:
                return "afternoon"
            else:
                return "evening"

        # Serialise time objects to HH:MM strings for the LLM
        slots = [
            {
                "slot_number": i + 1,
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "state": s.state,
                "period": _time_period(s.start_time.hour),
            }
            for i, s in enumerate(result.slots)
        ]
        available_count = sum(1 for s in slots if s["state"] == "available")
        return {
            "doctor_id": doctor_id,
            "date": appointment_date,
            "slot_duration_minutes": result.slot_duration,
            "slots": slots,
            "available_count": available_count,
        }
    except HTTPException as e:
        # 404 means doctor not available that day — useful info for the LLM
        if e.status_code == 404:
            return {"available": False, "message": f"Doctor has no availability on {appointment_date}."}
        return _http_err(e)
    except (ValueError, AttributeError) as e:
        return {"error": f"Invalid input: {e}"}
    except Exception as e:
        logger.error(f"get_doctor_slots_for_date tool error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 3. GET SLOTS RANGE  →  routers/doctor.py :: get_doctor_slots_range()
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def get_doctor_slots_range(
    doctor_id: str,
    days: int = 14,
) -> dict:
    """
    Get a day-by-day availability summary for a doctor over the next N days (max 30).
    Returns per-day: date, is_active, and how many slots are free.
    Use this when the user's preferred date is fully booked or they're flexible on date.
    """
    from api.v1.endpoints.doctor import get_doctor_slots_range as _handler

    try:
        result = await _handler(
            doctor_id=uuid.UUID(doctor_id),
            days=min(days, 30),
            db=_db(),
            current_user=_user(),
        )
        # Summarise each day: available + free slot count
        summary = []
        for day in result.days:
            free = sum(1 for s in day.slots if s.state == "available")
            summary.append({
                "date": str(day.available_date),
                "day_of_week": day.available_date.strftime("%A"),
                "is_active": day.is_active,
                "free_slots": free,
            })
        return {"doctor_id": doctor_id, "range_summary": summary}
    except HTTPException as e:
        return _http_err(e)
    except (ValueError, AttributeError) as e:
        return {"error": f"Invalid input: {e}"}
    except Exception as e:
        logger.error(f"get_doctor_slots_range tool error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 4. DIRECT BOOK  →  routers/appointment.py :: direct_book_appointment()
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def direct_book_appointment(
    doctor_id: str,
    appointment_date: str,
    start_time: str,
    end_time: str,
) -> dict:
    """
    Book an appointment for the current patient.
    appointment_date: YYYY-MM-DD   |   start_time / end_time: HH:MM (24-hr)
    ONLY call this after the user has explicitly confirmed the booking summary.
    """
    from api.v1.endpoints.appointment import direct_book_appointment as _handler

    try:
        payload = DirectBookDTO(
            doctor_id=uuid.UUID(doctor_id),
            appointment_date=date.fromisoformat(appointment_date),
            start_time=time.fromisoformat(start_time),
            end_time=time.fromisoformat(end_time),
        )
        result = await _handler(
            payload=payload,
            db=_db(),
            current_user=_user(),
        )
        return result   # already a plain dict from the handler
    except HTTPException as e:
        return _http_err(e)
    except (ValueError, AttributeError) as e:
        return {"error": f"Invalid input: {e}"}
    except Exception as e:
        logger.error(f"direct_book_appointment tool error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 5. GET PROFILE  →  routers/profile.py :: get_my_profile()
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def get_my_profile() -> dict:
    """
    Retrieve the current user's profile (name, contact info, city, etc.).
    Use when the user asks about their own account details.
    """
    from api.v1.endpoints.profile import get_my_profile as _handler

    try:
        result = await _handler(db=_db(), current_user=_user())
        # result is already a dict {"user": UserProfileResponse, ...}
        user_data = result["user"]
        return {
            "id": str(user_data.id),
            "email": user_data.email,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "gender": user_data.gender,
            "phone_number": user_data.phone_number,
            "city": user_data.city,
            "state": user_data.state,
            "address": user_data.address,
            "country": user_data.country,
            "date_of_birth": str(user_data.date_of_birth) if user_data.date_of_birth else None,
        }
    except HTTPException as e:
        return _http_err(e)
    except Exception as e:
        logger.error(f"get_my_profile tool error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 6. UPDATE PROFILE  →  routers/profile.py :: update_profile()
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def update_user_profile(
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    address: Optional[str] = None,
    country: Optional[str] = None,
    profile_image_url: Optional[str] = None,
) -> dict:
    """
    Update the current user's profile. Only pass fields the user explicitly asked to change.
    """
    from api.v1.endpoints.profile import update_profile as _handler

    # Build a dict with ONLY the non-None arguments
    update_data = {}
    if first_name is not None:
        update_data['first_name'] = first_name
    if last_name is not None:
        update_data['last_name'] = last_name
    if phone_number is not None:
        update_data['phone_number'] = phone_number
    if city is not None:
        update_data['city'] = city
    if state is not None:
        update_data['state'] = state
    if address is not None:
        update_data['address'] = address
    if country is not None:
        update_data['country'] = country
    if profile_image_url is not None:
        update_data['profile_image_url'] = profile_image_url

    if not update_data:
        return {"error": "No fields provided to update"}

    # Pydantic v2: use model_validate, not parse_obj
    user_update = BaseProfileDTO.model_validate(update_data)
    payload = ProfileUpdateRequest(user=user_update)

    try:
        result = await _handler(payload=payload, db=_db(), current_user=_user())
        return {
            "success": True,
            "updated_fields": list(update_data.keys()),
            "message": "Profile updated successfully.",
        }
    except HTTPException as e:
        return _http_err(e)
    except Exception as e:
        logger.error(f"update_user_profile tool error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# EXPORTED TOOL LIST
# ─────────────────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    resolve_appointment_date,
    search_doctors,
    get_doctor_slots_for_date,
    get_doctor_slots_range,
    direct_book_appointment,
    get_my_profile,
    update_user_profile,
]