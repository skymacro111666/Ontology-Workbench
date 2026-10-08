"""Fernet helper: roundtrip, ciphertext != plaintext, per-secret divergence."""

import pytest

from ontoworkbench.server.crypto import decrypt_str, encrypt_str, fernet_from_jwt_secret


def test_roundtrip_and_divergence() -> None:
    """Encrypt→decrypt roundtrips; a different secret must not decrypt."""
    f1, f2 = fernet_from_jwt_secret("a" * 64), fernet_from_jwt_secret("b" * 64)
    ct = encrypt_str(f1, "s3cret-pw")
    assert ct != "s3cret-pw" and "s3cret-pw" not in ct
    assert decrypt_str(f1, ct) == "s3cret-pw"
    with pytest.raises(Exception):  # noqa: B017 - Fernet raises InvalidToken
        decrypt_str(f2, ct)


def test_stable_key_for_same_secret() -> None:
    """The same secret derives the same key (restarts can still decrypt)."""
    a, b = fernet_from_jwt_secret("same-secret"), fernet_from_jwt_secret("same-secret")
    assert decrypt_str(b, encrypt_str(a, "x")) == "x"


def test_unicode_roundtrip() -> None:
    """Non-ASCII passwords survive the byte boundary."""
    f = fernet_from_jwt_secret("k" * 64)
    assert decrypt_str(f, encrypt_str(f, "密码-123")) == "密码-123"
