"""Admin key check for the endpoints that expose or change global state.

API_KEYS holds comma-separated ``name:scope:secret`` entries (same format as
the fascicoli fork). Only the ``admin`` scope unlocks anything here; ``site``
and ``developer`` entries are parsed so the variable can be shared, but they
grant nothing extra.

Rules:

- Admin endpoints (listing every saved question, deleting history, changing
  the live configuration, the evaluation dashboard, survey listings) need an
  ``X-API-Key`` header holding an admin key.
- With API_KEYS unset or without any admin entry, admin endpoints are denied
  (fail closed).
- Every other endpoint stays open, with or without a key: the site and the
  MCP server keep working without configuration.
"""

from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

HEADER = "x-api-key"

_ADMIN_RULES = [
    ("GET", re.compile(r"^/api/history$")),
    ("DELETE", re.compile(r"^/api/history(/.*)?$")),
    ("POST", re.compile(r"^/api/history/[^/]+/baseline-experts$")),
    ("PUT", re.compile(r"^/api/config$")),
    ("POST", re.compile(r"^/api/config/reload$")),
    ("*", re.compile(r"^/api/evaluation(/.*)?$")),
    ("GET", re.compile(r"^/api/surveys$")),
    ("GET", re.compile(r"^/api/surveys/stats/summary$")),
    ("GET", re.compile(r"^/api/surveys/chats/(evaluated|pending)$")),
    ("DELETE", re.compile(r"^/api/surveys(/.*)?$")),
    ("*", re.compile(r"^/(docs|redoc|openapi\.json)(/.*)?$")),
]


@dataclass(frozen=True)
class ApiKey:
    name: str
    scope: str
    secret: str


def parse_keys(raw: str) -> list[ApiKey]:
    keys = []
    for entry in raw.split(","):
        parts = entry.strip().split(":", 2)
        if len(parts) == 3 and parts[1] in {"admin", "site", "developer"} and parts[2]:
            keys.append(ApiKey(parts[0], parts[1], parts[2]))
    return keys


def find_key(keys: list[ApiKey], presented: str) -> ApiKey | None:
    match = None
    for k in keys:
        # Compare against every key so timing does not reveal which one matched.
        if hmac.compare_digest(k.secret.encode(), presented.encode()):
            match = k
    return match


def _normalize(path: str) -> str:
    path = re.sub(r"/{2,}", "/", path)
    return path.rstrip("/") or "/"


def is_admin_only(method: str, path: str) -> bool:
    method = "GET" if method == "HEAD" else method
    path = _normalize(path)
    return any((m == "*" or m == method) and rx.match(path) for m, rx in _ADMIN_RULES)


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


async def api_key_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or not is_admin_only(request.method, request.url.path):
        return await call_next(request)

    admin_keys = [k for k in parse_keys(os.getenv("API_KEYS", "")) if k.scope == "admin"]
    if not admin_keys:
        return _deny(403, "Admin endpoints are disabled: no admin key configured.")

    presented = request.headers.get(HEADER, "")
    if not presented:
        return _deny(401, "Admin key required.")
    key = find_key(admin_keys, presented)
    if key is None:
        return _deny(403, "Invalid admin key.")

    request.state.api_key_name = key.name
    return await call_next(request)
