"""Small validated types shared by the API request models."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator

Exchange = Literal["NSE", "BSE"]


def _no_nul(v: str) -> str:
    if "\x00" in v:
        raise ValueError("must not contain null characters")
    return v


def _no_nul_opt(v: str | None) -> str | None:
    return v if v is None else _no_nul(v)


# Postgres text cannot store NUL; without this a stray \x00 reached the database and returned a 500.
NoNul = Annotated[str, AfterValidator(_no_nul)]
OptNoNul = Annotated[str | None, AfterValidator(_no_nul_opt)]
