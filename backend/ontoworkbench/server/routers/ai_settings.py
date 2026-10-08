"""AI settings endpoints + the shared provider dependency (spec §2).

Config precedence: the user's ai_settings row over the AI_* env vars (env is
the bootstrap default). The API key is write-only — GET never returns it,
only hasKey + the last 4 characters for recognition.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.config import Settings
from ontoworkbench.core.ai import get_provider
from ontoworkbench.core.ai.base import AiConfig, ModelProvider
from ontoworkbench.core.ai.types import ModelRequest
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import AiSettingsRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

_audit = structlog.get_logger("ow.audit")


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SettingsIn(CamelModel):
    """PUT body: every field optional; apiKey omitted/empty = keep stored."""

    provider: str | None = Field(default=None, min_length=1, max_length=16)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)


def _merged_cfg(settings: Settings, user_id, session: Session) -> AiConfig:
    """Env config overlaid by the user's stored row (non-null fields win)."""
    cfg = AiConfig.from_env()
    row = AiSettingsRepository(session).get(user_id)
    if row is not None:
        cfg = AiConfig(
            provider=row.provider or cfg.provider,
            base_url=row.base_url if row.base_url is not None else cfg.base_url,
            api_key=row.api_key if row.api_key else cfg.api_key,
            model=row.model if row.model is not None else cfg.model,
        )
    return cfg


def get_ai_provider(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ModelProvider:
    """Resolve the provider from DB>env config; 503 with setup hint when absent."""
    cfg = _merged_cfg(request.app.state.settings, user.id, session)
    if not cfg.configured:
        raise ApiError(
            ErrorCode.AI_NOT_CONFIGURED,
            "AI provider is not configured",
            hint=(
                "set AI_MODEL_PROVIDER/AI_BASE_URL/AI_API_KEY/AI_MODEL in .env "
                "or via PUT /api/v1/ai/settings"
            ),
        )
    return get_provider(cfg)


def _has_row(user_id, session: Session) -> bool:
    """Whether the user has stored any settings row."""
    return AiSettingsRepository(session).get(user_id) is not None


@router.get("/settings")
def get_settings(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Read the settings; the key never leaves the backend."""
    env = AiConfig.from_env()
    row = AiSettingsRepository(session).get(user.id)
    if row is None:
        return respond(
            {
                "provider": env.provider,
                "baseUrl": env.base_url,
                "model": env.model,
                "hasKey": bool(env.api_key),
                "keyLast4": env.api_key[-4:] if env.api_key else None,
                "source": "env",
            }
        )
    key = row.api_key or env.api_key
    return respond(
        {
            "provider": row.provider,
            "baseUrl": row.base_url,
            "model": row.model,
            "hasKey": bool(key),
            "keyLast4": key[-4:] if key else None,
            "source": "db",
        }
    )


@router.put("/settings")
def put_settings(
    body: SettingsIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Partially update the settings; apiKey omitted/empty keeps the stored key."""
    fields: dict = {}
    if body.provider is not None:
        fields["provider"] = body.provider
    if body.base_url is not None:
        fields["base_url"] = body.base_url
    if body.api_key:
        fields["api_key"] = body.api_key
    if body.model is not None:
        fields["model"] = body.model
    AiSettingsRepository(session).upsert(user_id=user.id, **fields)
    session.commit()
    _audit.info("ai_settings.update", user_id=str(user.id), fields=sorted(fields))
    return respond(message="updated")


@router.get("/status")
def get_status(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Cheap configured-check for panels and wizards."""
    cfg = _merged_cfg(request.app.state.settings, user.id, session)
    return respond(
        {
            "configured": cfg.configured,
            "provider": cfg.provider,
            "model": cfg.model,
            "source": "db" if _has_row(user.id, session) else "env",
        }
    )


@router.post("/test")
async def test_connection(
    provider: ModelProvider = Depends(get_ai_provider),
) -> dict:
    """One-token probe; failures land as {ok: false, message} on the OK envelope."""
    t0 = time.perf_counter()
    try:
        resp = await provider.complete(
            ModelRequest(
                messages=[{"role": "user", "content": "Reply with exactly: pong"}], max_tokens=8
            )
        )
    except Exception as e:  # noqa: BLE001 - the probe reports any upstream failure
        return respond({"ok": False, "message": str(e)[:300]})
    return respond(
        {
            "ok": True,
            "latencyMs": round((time.perf_counter() - t0) * 1000, 1),
            "reply": resp.text[:40],
        }
    )
