"""Account machine credentials: mint/hash/resolve + env seeding (spec D11/D12).

Type credentials live side by side: jwt.py is the human session credential,
this module is the account's machine credential (GitHub-PAT semantics) —
authorization follows the credential type, enforced by the REST allowlist.
"""

from __future__ import annotations

import hashlib
import secrets

import structlog
from sqlalchemy.orm import Session

from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import AgentTokenRepository, UserRepository

TOKEN_PREFIX = "owag_"

_log = structlog.get_logger("ow.auth")


def mint() -> str:
    """Return a fresh token: owag_ + >=128 bits of urlsafe entropy."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex — the storage/lookup key (high-entropy random, no KDF needed)."""
    return hashlib.sha256(token.encode()).hexdigest()


def resolve(session: Session, token: str) -> tuple[User, str] | None:
    """owag_ token -> (bound user, label); None when unknown.

    The label comes from the DB row only — no client input participates,
    so audit attribution cannot be forged. Touches last_used_at (throttled).
    """
    if not token.startswith(TOKEN_PREFIX):
        return None
    row = AgentTokenRepository(session).get_by_hash(hash_token(token))
    if row is None:
        return None
    user = UserRepository(session).get(row.user_id)
    if user is None:
        return None
    AgentTokenRepository(session).touch(row)
    return user, row.label


def parse_env_tokens(raw: str) -> list[tuple[str, str]]:
    """'label:token,label:token' -> pairs; malformed entries are logged and skipped."""
    out: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, sep, tok = chunk.partition(":")
        if not sep or not label or not tok.startswith(TOKEN_PREFIX):
            _log.warning("agent_tokens.env_malformed", entry=chunk[:16])
            continue
        out.append((label, tok))
    return out


def seed_from_env(session: Session, raw: str) -> list[str]:
    """Bootstrap-only import (spec D12): bind the single admin, insert-only by label."""
    if not raw.strip():
        return []
    user = UserRepository(session).first()
    if user is None:
        _log.warning("agent_tokens.seed_skipped_no_user")
        return []
    repo = AgentTokenRepository(session)
    imported: list[str] = []
    for label, tok in parse_env_tokens(raw):
        if repo.get_by_label(user.id, label) is not None:
            continue
        repo.create(user.id, label, hash_token(tok), tok[:8])
        imported.append(label)
    session.commit()
    if imported:
        _log.info("agent_tokens.seeded", labels=imported)
    return imported
