import secrets
import logging
import urllib.parse
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel

from app.config import settings
from app.services.auth_service import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

def get_oauth_base_url(request: Request) -> str:
    """
    Returns the public base URL for OAuth callbacks.
    Prioritizes APP_BASE_URL if configured in .env.
    Otherwise handles X-Forwarded-Proto / X-Forwarded-Host headers
    and normalizes '127.0.0.1' -> 'localhost' to prevent Google's redirect_uri_mismatch.
    """
    if settings.app_base_url:
        return settings.app_base_url.rstrip("/")

    # Respect reverse proxies / Tailscale serve HTTPS headers
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host")
    if proto and host:
        return f"{proto}://{host}".rstrip("/")

    base = str(request.base_url).rstrip("/")
    # Replace 127.0.0.1 with localhost since Google OAuth explicitly allows localhost
    if "://127.0.0.1" in base:
        base = base.replace("://127.0.0.1", "://localhost")
    return base

class GoogleCredentialRequest(BaseModel):
    credential: str

class GoogleConfigRequest(BaseModel):
    client_id: str
    client_secret: str
    allowed_emails: Optional[str] = None

class EmergencyLoginRequest(BaseModel):
    token: str

@router.get("/status")
async def get_auth_status(request: Request):
    """Check current authentication status and user identity."""
    session_token = request.cookies.get("obrigado_session")
    user = auth_service.validate_session(session_token)
    base_url = get_oauth_base_url(request)
    return {
        "authenticated": user is not None,
        "user": user,
        "google_configured": auth_service.is_google_configured(),
        "auth_enabled": auth_service.is_auth_enabled(),
        "dev_mode": settings.dev_mode,
        "dev_user": {
            "email": settings.dev_user_email,
            "name": settings.dev_user_name
        },
        "google_client_id": settings.google_client_id if auth_service.is_google_configured() else None,
        "oauth_base_url": base_url,
        "suggested_redirect_uri": f"{base_url}/api/auth/google/callback"
    }

@router.post("/dev-login")
async def dev_login(request: Request, response: Response):
    """1-Click Local Dev Login bypass (only enabled when DEV_MODE=true)."""
    if not settings.dev_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev login is disabled in production (DEV_MODE=false)."
        )

    user = auth_service.upsert_user(
        email=settings.dev_user_email,
        name=settings.dev_user_name,
        picture="https://ui-avatars.com/api/?name=Local+Dev&background=6366f1&color=fff",
        user_id="local_dev_user"
    )
    session_token = auth_service.create_session(user["id"], user["email"])

    response.set_cookie(
        key="obrigado_session",
        value=session_token,
        httponly=True,
        max_age=86400 * settings.session_expire_days,
        samesite="lax",
        secure=request.url.scheme == "https"
    )
    logger.info(f"Local developer signed in via 1-Click Dev Mode: {user['email']}")
    return {"success": True, "redirect": "/", "user": user}

@router.get("/google/login")
async def google_login(request: Request):
    """Initiate Google OAuth2 redirect flow."""
    if not auth_service.is_google_configured():
        return RedirectResponse(url="/login?error=google_not_configured", status_code=status.HTTP_302_FOUND)

    # Determine redirect URI dynamically with smart localhost normalization
    redirect_uri = f"{get_oauth_base_url(request)}/api/auth/google/callback"
    state = secrets.token_urlsafe(16)
    auth_url = auth_service.build_google_auth_url(redirect_uri, state)

    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        max_age=600,
        samesite="lax",
        secure=request.url.scheme == "https"
    )
    return response

@router.get("/google/callback")
async def google_callback(request: Request):
    """Handle OAuth2 callback from Google."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    saved_state = request.cookies.get("oauth_state")

    if not code or not state or state != saved_state:
        logger.warning(f"OAuth state mismatch or missing code (state={state}, saved={saved_state})")
        return RedirectResponse(url="/login?error=invalid_oauth_state", status_code=status.HTTP_302_FOUND)

    redirect_uri = f"{get_oauth_base_url(request)}/api/auth/google/callback"

    try:
        token_data = auth_service.exchange_code(code, redirect_uri)
        id_token_str = token_data.get("id_token")
        if not id_token_str:
            raise ValueError("No id_token in Google token response")

        id_info = auth_service.verify_id_token(id_token_str)
        email = id_info.get("email")
        if not email:
            raise ValueError("No email in verified Google ID token")

        # Check authorization
        if not auth_service.is_email_authorized(email):
            logger.warning(f"Unauthorized login attempt by Google account: {email}")
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Access Denied - Obrigado</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4 font-sans">
                    <div class="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 sm:p-8 text-center shadow-2xl space-y-4">
                        <div class="w-12 h-12 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 flex items-center justify-center mx-auto text-xl font-bold">✕</div>
                        <h2 class="text-xl font-bold text-slate-100">Access Restricted</h2>
                        <p class="text-xs sm:text-sm text-slate-300">
                            Signed in as <span class="font-mono text-amber-300 font-semibold">{email}</span>.
                        </p>
                        <p class="text-xs text-slate-400">
                            This Google account is not on the authorized list for this Obrigado instance.
                            To grant access, add this email to <code class="bg-slate-800 px-1 py-0.5 rounded text-indigo-300">ALLOWED_EMAILS</code> in your <code class="text-slate-300">.env</code> file.
                        </p>
                        <div class="pt-2">
                            <a href="/login" class="inline-block px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition">Back to Sign In</a>
                        </div>
                    </div>
                </body>
                </html>
                """,
                status_code=status.HTTP_403_FORBIDDEN
            )

        name = id_info.get("name")
        picture = id_info.get("picture")
        user = auth_service.upsert_user(email, name, picture, id_info.get("sub"))
        session_token = auth_service.create_session(user["id"], email)

        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.delete_cookie("oauth_state")
        response.set_cookie(
            key="obrigado_session",
            value=session_token,
            httponly=True,
            max_age=86400 * settings.session_expire_days,
            samesite="lax",
            secure=request.url.scheme == "https"
        )
        logger.info(f"User signed in successfully with Google: {email}")
        return response

    except Exception as e:
        logger.error(f"Error handling Google OAuth callback: {e}", exc_info=True)
        return RedirectResponse(url=f"/login?error=auth_failed&detail={urllib.parse.quote(str(e))}", status_code=status.HTTP_302_FOUND)

@router.post("/google/verify-credential")
async def verify_google_credential(req: GoogleCredentialRequest, request: Request, response: Response):
    """Verify Google Identity Services client credential token and create session."""
    try:
        id_info = auth_service.verify_id_token(req.credential)
        email = id_info.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google token does not contain email.")

        if not auth_service.is_email_authorized(email):
            logger.warning(f"Unauthorized Google login attempt: {email}")
            raise HTTPException(status_code=403, detail=f"Email {email} is not authorized to access this instance.")

        name = id_info.get("name")
        picture = id_info.get("picture")
        user = auth_service.upsert_user(email, name, picture, id_info.get("sub"))
        session_token = auth_service.create_session(user["id"], email)

        response.set_cookie(
            key="obrigado_session",
            value=session_token,
            httponly=True,
            max_age=86400 * settings.session_expire_days,
            samesite="lax",
            secure=request.url.scheme == "https"
        )
        return {"success": True, "redirect": "/", "user": user}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify Google credential: {e}")
        raise HTTPException(status_code=400, detail=f"Token verification failed: {e}")

@router.post("/emergency-login")
async def emergency_login(req: EmergencyLoginRequest, request: Request, response: Response):
    """Emergency administrative login using the local token from data/.admin_token."""
    correct_token = auth_service.get_emergency_token()
    if not req.token or req.token.strip() != correct_token:
        raise HTTPException(status_code=401, detail="Invalid emergency token.")

    response.set_cookie(
        key="obrigado_session",
        value=correct_token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax",
        secure=request.url.scheme == "https"
    )
    logger.info("Admin logged in via local emergency token.")
    return {"success": True, "redirect": "/"}

@router.post("/configure")
async def configure_google_oauth(req: GoogleConfigRequest):
    """Configure or update Google OAuth Client credentials."""
    if not req.client_id.strip() or not req.client_secret.strip():
        raise HTTPException(status_code=400, detail="Client ID and Client Secret are required.")

    auth_service.save_google_config(req.client_id, req.client_secret, req.allowed_emails)
    return {
        "success": True,
        "message": "Google OAuth configuration saved successfully. You can now sign in with Google."
    }

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Sign out the current user and invalidate the session."""
    session_token = request.cookies.get("obrigado_session")
    if session_token:
        auth_service.delete_session(session_token)

    response.delete_cookie("obrigado_session")
    return {"success": True, "redirect": "/login"}
