"""Core-layer typed error (kept free of server imports per layering)."""

from __future__ import annotations


class CoreError(Exception):
    """Raised by core modules; the server layer converts it to an ApiError."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        """Store the machine code, human message, and optional hint."""
        self.code, self.message, self.hint = code, message, hint
        super().__init__(message)
