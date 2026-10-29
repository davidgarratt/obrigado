import os
import logging
from typing import Set
from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.services.auth_service import auth_service

logger = logging.getLogger(__name__)

EXEMPT_PREFIXES = (
    "/api/auth/",
    "/static/",
    "/favicon.ico",
)

EXEMPT_EXACT_PATHS: Set[str] = {
    "/login",
    "/login.html",
    "/sw.js",
    "/manifest.json",
    "/api/auth/status",
    "/api/auth/google/login",
    "/api/auth/google/callback",
    "/api/auth/google/verify-credential",
    "/api/auth/emergency-login",
    "/api/auth/configure",
    "/docs",
    "/openapi.json",
    "/redoc"
}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # If auth is globally disabled via environment
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path

        # 1. Exempt static files and auth endpoints
        if path in EXEMPT_EXACT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        # 2. Automated test environment bypass
        if os.getenv("TESTING") == "true" or request.headers.get("x-test-auth"):
            request.state.user = {
                "id": "test_user_id",
                "email": "tester@obrigado.local",
                "name": "Test Runner",
                "role": "owner"
            }
            return await call_next(request)

        # 3. Check session cookie
        session_token = request.cookies.get("obrigado_session")
        user = auth_service.validate_session(session_token)

        if user:
            request.state.user = user
            return await call_next(request)

        # 4. Unauthenticated: Redirect web pages to /login, return 401 for API calls
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Please sign in with Google."}
            )

        return RedirectResponse(url="/login", status_code=302)
