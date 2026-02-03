from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from database.postgres import get_db
from schemas.schemas import User, DoctorProfile,DoctorCategory
from schemas.profile_schema import (
    UserProfileResponse,
    DoctorProfileResponse,
    ProfileUpdateRequest,
    ProfileResponse
)
from dependencies.auth import get_current_user
from services.file_upload_service import upload_image

router = APIRouter(prefix="/profile", tags=["Profile"])

@router.get("/me")
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    response = {
        "user": UserProfileResponse.model_validate(current_user)
    }

    doctor = await db.scalar(
        select(DoctorProfile)
        .where(DoctorProfile.user_id == current_user.id)
    )

    if doctor:
        response["doctor_profile"] = DoctorProfileResponse.model_validate(doctor) # type: ignore

    return response

@router.put("/me/avatar")
async def update_profile_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload_result = await upload_image(file.file, folder="profile_images")

    current_user.profile_image_url = upload_result["url"]
    await db.commit()

    return {
        "message": "Profile image updated successfully",
        "image_url": upload_result["url"]
    }

@router.put("/me", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch doctor profile once
    doctor = await db.scalar(
        select(DoctorProfile)
        .where(DoctorProfile.user_id == current_user.id)
    )


    if payload.user:
        for field, value in payload.user.model_dump(exclude_unset=True).items():
            setattr(current_user, field, value)


    if payload.doctor:
        if current_user.role != "doctor":
            raise HTTPException(
                status_code=403,
                detail="Only doctors can update doctor profile"
            )

        if not doctor:
            raise HTTPException(
                status_code=404,
                detail="Doctor profile not found"
            )

        for field, value in payload.doctor.model_dump(exclude_unset=True).items():
            setattr(doctor, field, value)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update profile"
        )


    await db.refresh(current_user)
    if doctor:
        await db.refresh(doctor)

    return ProfileResponse(
        user=UserProfileResponse.model_validate(current_user),
        doctor_profile=(
            DoctorProfileResponse.model_validate(doctor)
            if doctor else None
        )
    )
