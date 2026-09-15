"""Tests for settings loading and .env bootstrap."""

from pathlib import Path

import pytest

from ontoworkbench.config import Settings, ensure_env_file


def test_defaults_with_tmp_env(tmp_path: Path, monkeypatch) -> None:
    """Test default values when loading settings with temporary .env file."""
    monkeypatch.chdir(tmp_path)
    ensure_env_file(tmp_path / ".env")
    s = Settings.load()
    assert s.port == 8734
    assert s.data_dir.name == "data"  # package-local default
    assert s.jwt_secret  # generated on first run
    assert s.db_url.startswith("sqlite:///")


def test_cli_overrides_env(monkeypatch, tmp_path: Path) -> None:
    """Test that CLI arguments override environment variables."""
    monkeypatch.setenv("OW_PORT", "9000")
    s = Settings.load({"port": 9100})
    assert s.port == 9100


def test_ensure_env_file_chmod_600(tmp_path: Path) -> None:
    """.env files land mode 0600 whether created or rewritten (spec §9.1)."""
    env = tmp_path / ".env"
    ensure_env_file(env)
    assert (env.stat().st_mode & 0o777) == 0o600
    ensure_env_file(env)  # idempotent on existing files too
    assert (env.stat().st_mode & 0o777) == 0o600


def test_jwt_secret_file_read_and_stripped(tmp_path: Path, monkeypatch) -> None:
    """OW_JWT_SECRET_FILE content becomes the secret, whitespace-stripped.

    chdir is load-bearing: the repo's real backend/.env carries an
    OW_JWT_SECRET, and pydantic's dotenv search is CWD-relative — without
    chdir that secret would satisfy jwt_secret and the file never loads.
    """
    monkeypatch.chdir(tmp_path)
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("  abc123def456abc123def456abc123def  \n", encoding="utf-8")
    monkeypatch.setenv("OW_JWT_SECRET_FILE", str(secret_file))
    monkeypatch.delenv("OW_JWT_SECRET", raising=False)
    s = Settings.load()
    assert s.jwt_secret == "abc123def456abc123def456abc123def"


def test_explicit_secret_beats_file(tmp_path: Path, monkeypatch) -> None:
    """An explicit OW_JWT_SECRET value wins over OW_JWT_SECRET_FILE."""
    monkeypatch.chdir(tmp_path)
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("OW_JWT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("OW_JWT_SECRET", "from-env")
    assert Settings.load().jwt_secret == "from-env"


def test_missing_secret_file_system_exits(tmp_path: Path, monkeypatch) -> None:
    """A missing OW_JWT_SECRET_FILE aborts with a message naming the variable.

    chdir is load-bearing here too: the real backend/.env would otherwise
    supply a non-empty OW_JWT_SECRET and mask the missing file entirely.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OW_JWT_SECRET_FILE", str(tmp_path / "nope.txt"))
    monkeypatch.delenv("OW_JWT_SECRET", raising=False)
    with pytest.raises(SystemExit, match="OW_JWT_SECRET_FILE"):
        Settings.load()
