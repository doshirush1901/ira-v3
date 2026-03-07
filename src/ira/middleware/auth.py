"""API key authentication for Ira's FastAPI endpoints."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ira.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

_PUBLIC_PATHS = frozenset({"/api/health", "/docs", "/openapi.json", "/redoc"})


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """Validate the Bearer token against the configured API_SECRET_KEY.

    Endpoints listed in ``_PUBLIC_PATHS`` are exempt.  When no secret key
    is configured the check is skipped (open access for development).
    """
    if request.url.path in _PUBLIC_PATHS:
        return

    secret = get_settings().app.api_secret_key.get_secret_value()
    if not secret:
        return

    if credentials is None or credentials.credentials != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
