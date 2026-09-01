"""Unit tests for the serve port-retry decision and flag→settings mapping."""

from __future__ import annotations

import errno
import socket
from collections.abc import Callable
from pathlib import Path

import pytest

from ontoworkbench.cli import MAX_PORT_ATTEMPTS, _probe_port, _serve_cli, resolve_serve_port
from ontoworkbench.config import Settings


def _always_busy(host: str, port: int) -> None:
    """Probe stub that reports every port as occupied."""
    raise OSError(errno.EADDRINUSE, "address already in use")


def _resolve(
    probe: Callable[[str, int], None],
    port: int = 8734,
) -> tuple[int, list[str]]:
    """Run resolve_serve_port with a recording warn sink."""
    warnings: list[str] = []
    chosen = resolve_serve_port("127.0.0.1", port, probe=probe, warn=warnings.append)
    return chosen, warnings


def test_first_free_port_is_returned_without_warnings() -> None:
    """A bindable start port is used as-is, silently."""
    chosen, warnings = _resolve(lambda host, port: None)
    assert chosen == 8734
    assert warnings == []


def test_busy_ports_are_bumped_until_free() -> None:
    """Occupied ports bump +1 with one warning line per bump (spec §6)."""

    def busy_below_8736(host: str, port: int) -> None:
        if port < 8736:
            raise OSError(errno.EADDRINUSE, "address already in use")

    chosen, warnings = _resolve(busy_below_8736)
    assert chosen == 8736
    assert warnings == ["port 8734 is in use — trying 8735", "port 8735 is in use — trying 8736"]


def test_gives_up_after_max_attempts() -> None:
    """All-busy ports fail with a clear error after MAX_PORT_ATTEMPTS tries."""
    warnings: list[str] = []
    with pytest.raises(OSError, match="8734-8743"):
        resolve_serve_port("127.0.0.1", 8734, probe=_always_busy, warn=warnings.append)
    assert len(warnings) == MAX_PORT_ATTEMPTS - 1


def test_non_addrinuse_error_propagates_immediately() -> None:
    """Bind errors other than EADDRINUSE are not retried (bumping cannot help)."""

    def unusable(host: str, port: int) -> None:
        raise OSError(errno.EADDRNOTAVAIL, "cannot assign requested address")

    warnings: list[str] = []
    with pytest.raises(OSError, match="cannot assign requested address"):
        resolve_serve_port("127.0.0.1", 8734, probe=unusable, warn=warnings.append)
    assert warnings == []


def test_probe_port_detects_a_real_listener() -> None:
    """The real socket probe reports an actively listening port as EADDRINUSE."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        taken = listener.getsockname()[1]
        with pytest.raises(OSError) as excinfo:
            _probe_port("127.0.0.1", taken)
    assert excinfo.value.errno == errno.EADDRINUSE


def test_unset_flags_leave_env_in_charge(monkeypatch, tmp_path) -> None:
    """No explicit --host/--port → the .env decides (CLI > env > defaults).

    A concrete typer default would ride along as an init kwarg and pin the
    field, silently overriding OW_HOST/OW_PORT — the original bug.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OW_HOST=10.0.0.5\nOW_PORT=9001\n")
    s = Settings.load(_serve_cli(None, None, None, None))
    assert (s.host, s.port) == ("10.0.0.5", 9001)


def test_explicit_flags_beat_env(monkeypatch, tmp_path) -> None:
    """Explicit --host/--port win over .env, and --port 0 stays meaningful."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OW_HOST=10.0.0.5\nOW_PORT=9001\n")
    s = Settings.load(_serve_cli("0.0.0.0", 0, None, None))
    assert (s.host, s.port) == ("0.0.0.0", 0)


def test_optional_dirs_pass_through_only_when_given() -> None:
    """--data-dir/--log-dir join the cli dict only when actually passed."""
    assert _serve_cli(None, None, None, None) == {}
    cli = _serve_cli(None, None, "/tmp/data", "/tmp/logs")
    assert cli == {"data_dir": Path("/tmp/data"), "log_dir": Path("/tmp/logs")}


def test_non_loopback_warning_is_a_json_log_event() -> None:
    """The warning rides the structlog pipeline, not bare stdout/stderr.

    A typer.echo line breaks the JSON log stream (one plain-text line amid
    parseable records); the event keeps every sink a uniform JSON feed.
    """
    from structlog.testing import capture_logs

    from ontoworkbench.cli import warn_non_loopback

    with capture_logs() as logs:
        warn_non_loopback("0.0.0.0")
    assert logs == [
        {
            "event": "serve.non_loopback",
            "host": "0.0.0.0",
            "hint": "place this instance behind a reverse proxy with HTTPS before exposing it",
            "log_level": "warning",
        }
    ]
