from fastapi import APIRouter, Depends, HTTPException, Request, Response,Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timezone, timedelta
from database.postgres import get_db
from schemas.schemas import (
    User, Role, UserSession, DoctorProfile, 
    DoctorCategory, DoctorCategoryMap, RoleEnum,PasswordResetToken
)
from datetime import date
from schemas.auth_schema import UserSignup, UserLogin, Token,DoctorSignup,ForgotPasswordRequest,ResetPasswordRequest
from core.config import ACCESS_TOKEN_EXPIRE_MINUTES,FRONTEND_URL
from core.security import (
    get_password_hash, verify_password, 
    create_access_token, create_refresh_token, hash_token,generate_reset_token
)
import hashlib
from core.mail import send_email
import secrets
from loguru import logger
router = APIRouter(
    # prefix='/auth',
    dependencies=[Depends(get_db)],tags=['Auth']
)

async def create_tokens_for_user(
    user,
    db: AsyncSession,
    response: Response,
    device_id: str | None = None,
    force: bool = False
):
    device_id = device_id or "unknown"

    # 🔍 Check existing session
    result = await db.execute(
        select(UserSession)
        .where(UserSession.user_id == user.id)
        .where(UserSession.is_active == True)
    )
    active_session = result.scalars().first()

    if active_session:
        if not force:
            raise HTTPException(
                status_code=409,
                detail="User already logged in on another device"
            )

        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id)
            .where(UserSession.is_active == True)
            .values(is_active=False)
        )
        await db.commit()
    result = await db.execute(
        select(Role).where(Role.id == user.role_id)
    )
    role = result.scalar_one()

    access_token = create_access_token(
        subject=user.id,
        payload={
            "role": role.name.value,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    refresh_token = create_refresh_token()

    db_session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_token),
        device_id=device_id,
        is_active=True,
        last_used_at=datetime.now(timezone.utc)
    )

    db.add(db_session)
    await db.commit()

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax"
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token
    }

def clear_auth_cookies(response: Response):
    response.delete_cookie("refresh_token")

@router.post("/signup", response_model=Token)
async def signup(
    user_in: UserSignup,
    response: Response,
    doctor_data: DoctorSignup | None = None,
    db: AsyncSession = Depends(get_db)
):
    
    existing_user = (
        await db.execute(
            select(User).where(User.email == user_in.email)
        )
    ).scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    role = (
        await db.execute(
            select(Role).where(Role.name == user_in.role)
        )
    ).scalar_one_or_none()

    if not role:
        role = Role(name=user_in.role)
        db.add(role)
        await db.flush()  
    if user_in.role == RoleEnum.PATIENT and doctor_data is not None:
        raise HTTPException(
            status_code=400,
            detail="Doctor details are not allowed for patient signup"
        )

    if user_in.role == RoleEnum.DOCTOR and not doctor_data:
        raise HTTPException(
            status_code=400,
            detail="Doctor details are required"
        )
    if not user_in.date_of_birth:
        raise HTTPException(
            status_code=400,
            detail="Date of birth is required"
        )

    today = date.today()

    if user_in.date_of_birth > today:
        raise HTTPException(
            status_code=400,
            detail="Date of birth cannot be in the future"
        )
    user = User(
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        gender=user_in.gender,
        date_of_birth=user_in.date_of_birth,
        role_id=role.id
    )

    db.add(user)
    await db.flush()  
    if user_in.role == RoleEnum.DOCTOR and doctor_data is not None:
        doctor = DoctorProfile(
            user_id=user.id,
            qualifications=doctor_data.qualifications,
            experience_years=doctor_data.experience_years
        )
        db.add(doctor)
        await db.flush()  

        for category_name in doctor_data.category_names:
            category = (
                await db.execute(
                    select(DoctorCategory)
                    .where(DoctorCategory.name == category_name)
                )
            ).scalar_one_or_none()

            if not category:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {category_name}"
                )

            db.add(
                DoctorCategoryMap(
                    doctor_id=doctor.id,
                    category_id=category.id
                )
            )

    await db.commit()

    return await create_tokens_for_user(user, db, response)

@router.post("/login", response_model=Token)
async def login(
    user_in: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    user = (
        await db.execute(
            select(User).where(User.email == user_in.email)
        )
    ).scalar_one_or_none()

    if not user or not verify_password(user_in.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return await create_tokens_for_user(
        user=user,
        db=db,
        response=response,
        device_id=user_in.device_id,
        force=user_in.force  
    )

@router.post("/refresh-token", response_model=Token)
async def refresh_token(
    response: Response,
    refresh_token: str, 
    db: AsyncSession = Depends(get_db)
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    hashed_rt = hash_token(refresh_token)
    
    # Find session (Async)
    result = await db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == hashed_rt)
    )
    session_entry = (await db.execute(
    select(UserSession).where(
        UserSession.refresh_token_hash == hashed_rt
    )
    )).scalar_one_or_none()


    if not session_entry or not session_entry.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    result = await db.execute(select(User).where(User.id == session_entry.user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Rotation: Mark old inactive
    session_entry.is_active = False 
    
    # Generate new pair
    return await create_tokens_for_user(user, db, response, session_entry.device_id)

@router.post("/logout")
async def logout(
    refresh_token: str ,
    db: AsyncSession = Depends(get_db)
):
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Refresh token missing"
        )

    hashed_token = hash_token(refresh_token)
    logger.debug(f"\n\n\n\n Refresh hash {hashed_token}")
    # Find active session
    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == hashed_token,
            UserSession.is_active == True
        )
    )
    sessions = result.scalars().all()
    if not sessions:
        logger.debug("no sessions")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    for session in sessions:
        logger.debug("is session")
        session.is_active = False
        logger.debug("session ended")

    await db.commit()

    return {"message": "Logged out successfully"}

@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    email = payload.email

    user = (
        await db.execute(
            select(User).where(User.email == email)
        )
    ).scalar_one_or_none()

    if not user:
        return {"message": "If email exists, reset link sent"}

    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    reset_entry = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)
    )

    db.add(reset_entry)
    await db.commit()

    reset_link = f"{FRONTEND_URL}/reset-password?token={token}"

    send_email(
        to_email=user.email,
        subject="Reset Your Password",
        html=f"""
        <p>Click below to reset your password:</p>
        <a href="{reset_link}">{reset_link}</a>
        <p>This link expires in 15 minutes.</p>
        """
    )

    return {"message": "Reset link sent"}

@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    token = payload.token
    new_password = payload.new_password
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    record = (  
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used == False,
                PasswordResetToken.expires_at > datetime.now(timezone.utc)
            )
        )
    ).scalar_one_or_none()

    if not record:
        raise HTTPException(400, "Invalid or expired token")

    user = await db.get(User, record.user_id)

    if not user:
        raise HTTPException(404, "User not found")

    user.password_hash = get_password_hash(new_password)
    record.used = True

    await db.commit()

    return {"message": "Password reset successful"}

@router.get("/validate")
async def validate_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Not authenticated")

    hashed_token = hash_token(refresh_token)

    result = await db.execute(
        select(UserSession)
        .where(
            UserSession.refresh_token_hash == hashed_token,
            UserSession.is_active == True
        )
    )

    session = result.scalar_one_or_none()

    if not session:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Session expired")

    # Optional: update last seen
    session.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    user = await db.get(User, session.user_id)

    return {
        "authenticated": True,
    }
