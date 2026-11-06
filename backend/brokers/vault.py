"""Encrypt broker secrets and tokens at rest (Fernet: AES-128-CBC + HMAC-SHA256)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from backend.core.config import settings


class VaultError(Exception):
    pass


def _fernet() -> Fernet:
    seed = settings.BROKER_ENCRYPTION_KEY or ("broker:" + settings.SECRET_KEY)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()))


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        raise VaultError("Stored broker details can no longer be read (the server's encryption key changed). Connect again.") from None
