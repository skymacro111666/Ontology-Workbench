"""JWT issue/verify (HS256, 7-day default)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

_TTL_DAYS = 7


def create_token(
    user_id: str, secret: str, expires_at: datetime | None = None
) -> tuple[str, datetime]:
    """Return (token, expiry) for the given user."""
    exp = expires_at or datetime.now(UTC) + timedelta(days=_TTL_DAYS)
    token = jwt.encode({"sub": user_id, "exp": exp, "jti": uuid4().hex}, secret, algorithm="HS256")
    return token, exp


def decode_token(token: str, secret: str) -> str | None:
    """Return user_id or None (invalid/expired)."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return str(sub) if sub is not None else None
