"""Make the calculation endpoints fail with a clear 422 instead of a 500 on extreme or non-finite numbers.

Inputs like 1e30, 99999999999999999999 or a bare NaN can overflow a calculation or produce an infinite result that
JSON cannot carry. Those are bad inputs, not server faults."""
from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

RANGE_MSG = "These numbers are too large or extreme to calculate. Check the inputs for typos."


def _err(status: int, msg: str) -> JSONResponse:
    return JSONResponse({"detail": msg}, status_code=status)


class SafeRoute(APIRoute):
    """Turns arithmetic overflow and non-finite results into a 422 for the routes that use it."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def safe(request: Request) -> Response:
            try:
                return await handler(request)
            except ArithmeticError:  # OverflowError, ZeroDivisionError, FloatingPointError
                return _err(422, RANGE_MSG)
            except ValueError as e:
                if "JSON compliant" in str(e) or "math domain" in str(e) or "math range" in str(e):
                    return _err(422, RANGE_MSG)
                raise

        return safe


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Like FastAPI's default 422, but never echoes the submitted value, which may be NaN or huge and cannot be encoded."""
    errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "invalid"), "type": e.get("type", "")} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
