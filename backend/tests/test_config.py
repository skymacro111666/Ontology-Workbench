"""Tests for settings loading and .env bootstrap."""

from pathlib import Path

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
