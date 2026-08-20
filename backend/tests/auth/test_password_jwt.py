"""Unit tests for password hashing and token round-trip."""

from datetime import UTC, datetime, timedelta

from ontoworkbench.auth.jwt import create_token, decode_token
from ontoworkbench.auth.password import hash_password, verify_password

# pyjwt >=2.13 warns on HMAC keys below the RFC 7518 recommended 32 bytes;
# real secrets come from OW_JWT_SECRET (64 hex chars), tests match that length.
SECRET = "t" * 32
WRONG_SECRET = "w" * 32


def test_password_roundtrip() -> None:
    """Hash then verify round-trips; wrong password fails."""
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip_and_expiry() -> None:
    """Token decodes with the right secret; wrong secret/expired yield None."""
    tok, exp = create_token("uid-1", SECRET)
    assert decode_token(tok, SECRET) == "uid-1"
    assert decode_token(tok, WRONG_SECRET) is None
    expired, _ = create_token("uid-1", SECRET, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert decode_token(expired, SECRET) is None
    assert exp > datetime.now(UTC)
