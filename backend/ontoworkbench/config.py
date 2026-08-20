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
    log_level: str = "INFO"

    @classmethod
    def load(cls, cli: dict | None = None) -> Settings:
        """Build settings with precedence CLI > env > defaults."""
        s = cls(**(cli or {}))
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
