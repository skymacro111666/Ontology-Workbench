"""argon2id password hashing."""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()  # argon2id by default


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2id."""
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Check plaintext against an argon2id hash."""
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
