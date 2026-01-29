from datetime import datetime, timedelta,timezone
from typing import Optional, Union, Any
from jose import jwt
from passlib.context import CryptContext
import secrets
import hashlib
from core.config import SECRET_KEY,ALGORITHM,ACCESS_TOKEN_EXPIRE_MINUTES


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain_password: str, hashed_password) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(
    subject: Union[str, Any],
    payload: dict,
    expires_delta: Optional[timedelta]
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=int(ACCESS_TOKEN_EXPIRE_MINUTES))

    to_encode = {
        "sub": str(subject),
        "exp": expire,
        **payload
    }

    encoded_jwt = jwt.encode(
        to_encode,
        str(SECRET_KEY),
        algorithm=str(ALGORITHM)
    )
    return encoded_jwt

def create_refresh_token() -> str:
    # Generate a random secure string (opaque token)
    return secrets.token_urlsafe(64)

def hash_token(token: str) -> str:
    # We store the hash of the refresh token in the DB, not the raw token
    return hashlib.sha256(token.encode()).hexdigest()

def generate_reset_token():
    raw_token = secrets.token_urlsafe(48)
    hashed = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, hashed