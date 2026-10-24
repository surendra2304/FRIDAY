"""
FRIDAY/apps/core/src/friday_core/error_envelope.py — FRIDAY Unified Error Handling Envelope.

Standard error response format across ALL agents with consistent
HTTP status codes and error codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

router = APIRouter()


# Standard error codes
ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


@dataclass
class ErrorEnvelope:
    """Standard error envelope."""
    error: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.error}


def create_error_response(status_code: int, message: str, details: dict | None = None) -> JSONResponse:
    """Create a standard error response."""
    error_code = ERROR_CODES.get(status_code, "UNKNOWN_ERROR")
    error_data = {
        "code": error_code,
        "message": message,
    }
    if details:
        error_data["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"error": error_data},
    )


def create_error_exception(status_code: int, message: str, details: dict | None = None) -> HTTPException:
    """Create a standard HTTPException."""
    detail = {"code": ERROR_CODES.get(status_code, "UNKNOWN_ERROR"), "message": message}
    if details:
        detail["details"] = details
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/errors/codes")
async def list_error_codes():
    """List all standard error codes."""
    return {"error_codes": ERROR_CODES}


@router.get("/errors/health")
async def error_envelope_health():
    """Check error envelope health."""
    return {"status": "operational", "envelope": "standard"}


@router.post("/errors/demo")
async def demo_error(status_code: int = 500, message: str = "Demo error"):
    """Demonstrate error envelope."""
    return create_error_response(status_code, message)
