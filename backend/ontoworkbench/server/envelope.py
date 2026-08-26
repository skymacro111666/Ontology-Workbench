"""Unified response envelope + error codes (spec §6)."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel

from ontoworkbench.observability.middleware import request_id_ctx

T = TypeVar("T")


class ErrorCode(StrEnum):
    """Machine-readable response codes."""

    OK = "OK"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    SETUP_DONE = "SETUP_DONE"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_FILENAME = "DUPLICATE_FILENAME"
    DUPLICATE_ENTITY = "DUPLICATE_ENTITY"
    EDIT_CONFLICT = "EDIT_CONFLICT"
    PARSE_FAILED = "PARSE_FAILED"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HTTP_OF = {
    ErrorCode.OK: 200,
    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    ErrorCode.SETUP_DONE: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.DUPLICATE_FILENAME: 409,
    ErrorCode.DUPLICATE_ENTITY: 409,
    ErrorCode.EDIT_CONFLICT: 409,
    ErrorCode.PARSE_FAILED: 400,
    ErrorCode.UPLOAD_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_FORMAT: 415,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.INTERNAL_ERROR: 500,
}


class Envelope(BaseModel, Generic[T]):
    """Five constant fields on every response."""

    code: str
    message: str
    data: T | None = None
    hint: str | None = None
    request_id: str


class ApiError(Exception):
    """Raise anywhere; handlers convert to an Envelope."""

    def __init__(self, code: ErrorCode, message: str, hint: str | None = None) -> None:
        """Store the error code, human message, and optional hint."""
        self.code, self.message, self.hint = code, message, hint
        super().__init__(message)


def respond(data: object = None, message: str = "success") -> dict:
    """Build a five-field success envelope carrying the current request id."""
    return {
        "code": ErrorCode.OK.value,
        "message": message,
        "data": data,
        "hint": None,
        "request_id": request_id_ctx.get(),
    }


def error_body(code: ErrorCode, message: str, hint: str | None = None) -> dict:
    """Build a five-field error envelope (handlers and the SPA mount share it)."""
    return {
        "code": code.value,
        "message": message,
        "data": None,
        "hint": hint,
        "request_id": request_id_ctx.get(),
    }
