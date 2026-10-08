"""Fernet encryption for DB-connection passwords (spec §3).

Key = sha256(jwt_secret): no new secret to provision, and rotating the JWT
secret intentionally invalidates stored ciphertexts (re-enter passwords).
Threat model: ow.db stolen — not filesystem access (same as .env).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def fernet_from_jwt_secret(secret: str) -> Fernet:
    """Derive a stable Fernet key from the boot-time JWT secret."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_str(f: Fernet, plain: str) -> str:
    """Encrypt a UTF-8 string to an opaque token."""
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_str(f: Fernet, token: str) -> str:
    """Decrypt a token produced by encrypt_str."""
    return f.decrypt(token.encode("ascii")).decode("utf-8")
