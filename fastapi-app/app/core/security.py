from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"

# Bcrypt only uses the first 72 bytes of the password (UTF-8).
def _password_bytes(plain: str) -> bytes:
    b = plain.encode("utf-8")
    if len(b) > 72:
        return b[:72]
    return b


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        _password_bytes(password),
        bcrypt.gensalt(),
    ).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            _password_bytes(plain),
            hashed.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


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
