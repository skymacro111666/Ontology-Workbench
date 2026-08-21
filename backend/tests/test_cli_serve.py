"""Unit tests for the serve port-retry decision (spec §6/§10)."""

from __future__ import annotations

import errno
import socket
from collections.abc import Callable

import pytest

from ontoworkbench.cli import MAX_PORT_ATTEMPTS, _probe_port, resolve_serve_port


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
