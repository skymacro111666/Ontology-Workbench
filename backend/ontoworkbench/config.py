"""Application settings loaded from CLI args > environment (.env) > defaults."""

from __future__ import annotations

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGE_ROOT = Path(__file__).parent


class Settings(BaseSettings):
    """Runtime configuration; field env names are OW_*."""

    model_config = SettingsConfigDict(env_prefix="OW_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8734
    data_dir: Path = _PACKAGE_ROOT / "data"
    log_dir: Path = _PACKAGE_ROOT / "logs"
    db_url: str = ""  # resolved in load(): sqlite under data_dir
    jwt_secret: str = ""
    # Docker-secrets style (spec §9.2): read the JWT secret from a file
    # instead of the env; an explicit OW_JWT_SECRET still wins.
    jwt_secret_file: str = ""
    log_level: str = "INFO"
    # Export site: by default the API only writes under {data_dir}/exports/
    # (the force flag clears the target dir, so an unrestricted out_dir is a
    # wipe-any-directory primitive). Opt back into arbitrary paths for
    # single-admin self-hosted use with OW_EXPORT_ALLOW_ANY_PATH=1.
    export_allow_any_path: bool = False
    # Y-axis debounce: mutations land in memory, files flush after this many
    # seconds of quiet (OW_AUTOSAVE_DEBOUNCE_S).
    autosave_debounce_s: float = 3.0
    # SHACL validation: escape-hatch bound, waiting UX by design (spec
    # §2.2 — spike measured go.owl at ~33s end to end).
    validate_timeout_s: float = 300.0
    # One-shot seeding source for agent tokens (spec D12): insert-only at
    # boot, then the DB is authoritative — revocation goes through the API.
    agent_tokens: str = ""

    @classmethod
    def load(cls, cli: dict | None = None) -> Settings:
        """Build settings with precedence CLI > env > defaults."""
        s = cls(**(cli or {}))
        # _FILE mode (spec §9.2): explicit value always wins; content stripped.
        if not s.jwt_secret and s.jwt_secret_file:
            path = Path(s.jwt_secret_file)
            if not path.is_file():
                raise SystemExit(
                    f"OW_JWT_SECRET_FILE points to a missing file: {path} "
                    "(fix the path, or set OW_JWT_SECRET instead)"
                )
            s.jwt_secret = path.read_text(encoding="utf-8").strip()
        # Handle empty string env vars that should use defaults
        if not s.data_dir.name:
            s.data_dir = _PACKAGE_ROOT / "data"
        if not s.log_dir.name:
            s.log_dir = _PACKAGE_ROOT / "logs"
        if not s.db_url:
            s.db_url = f"sqlite:///{s.data_dir / 'ow.db'}"
        return s


def ensure_env_file(env_path: Path) -> None:
    """Create .env from template if missing; inject a JWT secret if empty."""
    example = _PACKAGE_ROOT.parent / ".env.example"
    if not env_path.exists():
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    text = env_path.read_text(encoding="utf-8")
    if "OW_JWT_SECRET=" in text and not text.split("OW_JWT_SECRET=")[1].splitlines()[0].strip():
        text = text.replace("OW_JWT_SECRET=", f"OW_JWT_SECRET={secrets.token_hex(32)}", 1)
        env_path.write_text(text, encoding="utf-8")
    # Secret material on disk: tighten to 0600 on every path (create or
    # inject), independent of umask (spec §9.1); chmod is idempotent.
    env_path.chmod(0o600)
