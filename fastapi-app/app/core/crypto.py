"""Encrypt / decrypt LLM API keys at rest (Fernet)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    raw = (s.fernet_key or "").strip()
    if not raw:
        raise RuntimeError(
            "FERNET_KEY is not set. Generate with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(raw.encode() if isinstance(raw, str) else raw)


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(blob: bytes) -> str:
    try:
        return _fernet().decrypt(blob).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Could not decrypt credential (wrong FERNET_KEY?)") from e


def mask_key(s: str, keep: int = 4) -> str:
    s = s.strip()
    if len(s) <= keep * 2:
        return "***"
    return f"{s[:keep]}…{s[-keep:]}"
