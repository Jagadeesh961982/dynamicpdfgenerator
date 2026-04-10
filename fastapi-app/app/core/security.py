from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject_user_id: str, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_expire_minutes)
    to_encode: dict[str, Any] = {"sub": subject_user_id, "exp": expire}
    if extra:
        to_encode.update(extra)
    return jwt.encode(to_encode, s.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[JWT_ALGORITHM])


def parse_user_id(token: str) -> str:
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            raise ValueError("invalid token")
        return sub
    except JWTError as e:
        raise ValueError("invalid token") from e
