from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta
from database.postgres import get_db
from schemas.schemas import (
    User, Role, UserSession, DoctorProfile, 
    DoctorCategory, DoctorCategoryMap, RoleEnum
)
from schemas.auth_schema import UserSignup, UserLogin, Token,DoctorSignup
from core.config import ACCESS_TOKEN_EXPIRE_MINUTES
from core.security import (
    get_password_hash, verify_password, 
    create_access_token, create_refresh_token, hash_token
)

router = APIRouter(
    dependencies=[Depends(get_db)]
)

async def create_tokens_for_user(
    user,
    db: AsyncSession,
    response: Response,
    device_id: str | None = None
):
    device_id = device_id or "unknown"
    print("\n\n\nUser: ",user)
    # 1️⃣ Check for existing active session
    result = await db.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.is_active == True
        )
    )
    active_session = result.scalars().first()

    if active_session:
        # Same device already logged in
        if active_session.device_id == device_id:
            raise HTTPException(
                status_code=409,
                detail="This device is already logged in. Logout there first."
            )

        # Different device already logged in
        raise HTTPException(
            status_code=409,
            detail="User is already logged in on another device. Logout there first."
        )

    # 2️⃣ Generate tokens
    access_token = create_access_token(
        subject=str(user.id),
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    raw_refresh_token = create_refresh_token()

    # 3️⃣ Create new active session (SAFE now)
    db_session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(raw_refresh_token),
        device_id=device_id,
        user_agent="FastAPI Client",
        is_active=True,
        last_used_at=datetime.now(timezone.utc)
    )

    db.add(db_session)
    await db.commit()

    # 4️⃣ Set Refresh Token in HTTPOnly Cookie
    response.set_cookie(
        key="refresh_token",
        value=raw_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax"
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh_token,
        "token_type": "bearer"
    }
@router.post("/signup", response_model=Token)
async def signup(
    user_in: UserSignup,
    response: Response,
    doctor_data: DoctorSignup | None = None,
    db: AsyncSession = Depends(get_db)
):
    
    # 1. Check email
    result = await db.execute(select(User).where(User.email == user_in.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Get Role
    result = await db.execute(select(Role).where(Role.name == user_in.role))
    role = result.scalars().first()

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
    # 3. Create User
    user = User(
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        gender=user_in.gender,
        date_of_birth=user_in.date_of_birth,
        role_id=role.id
    )
    print("\n\n\nUsers: ",user)
   
    # 4. Doctor-specific logic
    if user_in.role == RoleEnum.DOCTOR:

        if not doctor_data:
            raise HTTPException(
                status_code=400,
                detail="Doctor details are required"
            )

        doctor = DoctorProfile(
            user_id=user.id,
            qualifications=doctor_data.qualifications,
            experience_years=doctor_data.experience_years
        )
        db.add(doctor)
        await db.flush()

        for category_name in doctor_data.category_names:
            result = await db.execute(
                select(DoctorCategory).where(DoctorCategory.name == category_name)
            )
            category = result.scalars().first()

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
async def login(user_in: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    # Async query
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalars().first()

    if not user or not verify_password(user_in.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is inactive")

    return await create_tokens_for_user(user, db, response, user_in.device_id)

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
    session_entry = result.scalars().first()

    if not session_entry or not session_entry.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Access related user explicitly (Lazy loading doesn't work well in async without options)
    # We load the user based on the session's user_id
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
    response: Response,
    refresh_token: str ,
    db: AsyncSession = Depends(get_db)
):
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Refresh token missing"
        )

    hashed_token = hash_token(refresh_token)

    # Find active session
    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == hashed_token,
            UserSession.is_active == True
        )
    )
    session = result.scalars().first()

    if not session:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )

    # Invalidate session
    session.is_active = False
    await db.commit()

    return {"message": "Logged out successfully"}
