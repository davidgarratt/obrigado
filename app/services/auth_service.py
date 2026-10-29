import os
import secrets
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path

import google.oauth2.id_token
import google.auth.transport.requests

from app.config import settings
from app.database import get_db_connection, utc_now_iso

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

class AuthService:
    def __init__(self):
        self._emergency_token = self._resolve_or_create_emergency_token()

    def _resolve_or_create_emergency_token(self) -> str:
        """Create or load a local emergency token for administrative access before OAuth setup."""
        token_file = settings.data_dir / ".admin_token"
        if token_file.exists():
            try:
                t = token_file.read_text(encoding="utf-8").strip()
                if t:
                    return t
            except Exception:
                pass

        new_token = f"obrigado_adm_{secrets.token_hex(16)}"
        try:
            token_file.write_text(new_token, encoding="utf-8")
            logger.info("Created local emergency admin token in data/.admin_token")
        except Exception as e:
            logger.warning(f"Could not write admin token file: {e}")
        return new_token

    def get_emergency_token(self) -> str:
        return self._emergency_token

    def is_google_configured(self) -> bool:
        return bool(settings.google_client_id and settings.google_client_secret)

    def is_auth_enabled(self) -> bool:
        return settings.auth_enabled

    def get_allowed_emails_list(self) -> List[str]:
        raw = settings.allowed_emails or os.getenv("ALLOWED_EMAILS", "")
        if not raw:
            return []
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def is_email_authorized(self, email: str) -> bool:
        """
        Check if email is authorized to access Obrigado.
        If ALLOWED_EMAILS is configured, only those emails can log in.
        If ALLOWED_EMAILS is not yet configured, the first user to log in becomes the authorized owner.
        """
        norm_email = email.strip().lower()
        allowed = self.get_allowed_emails_list()
        if allowed:
            return norm_email in allowed

        # If no allowed emails defined yet, check existing users
        conn = get_db_connection()
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            # First user to log in is automatically authorized
            conn.close()
            return True

        # If users exist, check if this email already exists
        existing = conn.execute("SELECT 1 FROM users WHERE LOWER(email) = ?", (norm_email,)).fetchone()
        conn.close()
        return bool(existing)

    def build_google_auth_url(self, redirect_uri: str, state: str) -> str:
        """Generate the Google OAuth2 authorization redirect URL."""
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account"
        }
        encoded = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
        return f"{GOOGLE_AUTH_URL}?{encoded}"

    def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code with Google token endpoint."""
        payload = {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        res = requests.post(GOOGLE_TOKEN_URL, data=payload, timeout=10)
        if not res.ok:
            logger.error(f"Failed to exchange Google OAuth code: {res.status_code} {res.text}")
            raise ValueError(f"Google token exchange failed: {res.text}")
        return res.json()

    def verify_id_token(self, id_token_str: str) -> Dict[str, Any]:
        """Verify and decode a Google ID token."""
        req = google.auth.transport.requests.Request()
        client_id = settings.google_client_id if settings.google_client_id else None
        id_info = google.oauth2.id_token.verify_oauth2_token(id_token_str, req, client_id)
        return id_info

    def upsert_user(self, email: str, name: Optional[str] = None, picture: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Create or update user in the users table."""
        now = utc_now_iso()
        norm_email = email.strip().lower()
        uid = user_id or str(secrets.token_hex(12))

        conn = get_db_connection()
        with conn:
            existing = conn.execute("SELECT id, role FROM users WHERE LOWER(email) = ?", (norm_email,)).fetchone()
            if existing:
                uid = existing["id"]
                conn.execute(
                    "UPDATE users SET name = COALESCE(?, name), picture = COALESCE(?, picture), last_login_at = ? WHERE id = ?",
                    (name, picture, now, uid)
                )
                role = existing["role"]
            else:
                count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                role = "owner" if count == 0 else "user"
                conn.execute(
                    "INSERT INTO users (id, email, name, picture, role, created_at, last_login_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, norm_email, name or norm_email.split("@")[0], picture, role, now, now)
                )
        conn.close()

        return {
            "id": uid,
            "email": norm_email,
            "name": name or norm_email.split("@")[0],
            "picture": picture,
            "role": role
        }

    def create_session(self, user_id: str, email: str) -> str:
        """Create a secure session token valid for session_expire_days."""
        token = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(days=settings.session_expire_days)

        conn = get_db_connection()
        with conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, email, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (token, user_id, email.strip().lower(), expires_at.isoformat(), created_at.isoformat())
            )
        conn.close()
        return token

    def validate_session(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Validate session token and return user info if valid."""
        if not token:
            return None

        # Check emergency token
        if token == self._emergency_token:
            return {
                "id": "emergency_admin",
                "email": "admin@obrigado.local",
                "name": "Local Administrator",
                "picture": None,
                "role": "owner",
                "is_emergency": True
            }

        conn = get_db_connection()
        now_iso = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            """
            SELECT s.token, s.expires_at, u.id, u.email, u.name, u.picture, u.role
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ?
            """,
            (token,)
        ).fetchone()

        if not row:
            conn.close()
            return None

        if row["expires_at"] < now_iso:
            with conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.close()
            return None

        conn.close()
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "picture": row["picture"],
            "role": row["role"]
        }

    def delete_session(self, token: Optional[str]):
        """Remove a session token from the database."""
        if not token:
            return
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.close()

    def save_google_config(self, client_id: str, client_secret: str, allowed_emails: Optional[str] = None):
        """Save Google credentials into environment and update settings."""
        settings.google_client_id = client_id.strip()
        settings.google_client_secret = client_secret.strip()
        if allowed_emails is not None:
            settings.allowed_emails = allowed_emails.strip()

        env_file = settings.base_dir / ".env"
        lines = []
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()

        updated_keys = {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"}
        if allowed_emails is not None:
            updated_keys.add("ALLOWED_EMAILS")

        new_lines = []
        for line in lines:
            key = line.split("=")[0].strip() if "=" in line else ""
            if key in updated_keys:
                continue
            new_lines.append(line)

        new_lines.append(f"GOOGLE_CLIENT_ID={settings.google_client_id}")
        new_lines.append(f"GOOGLE_CLIENT_SECRET={settings.google_client_secret}")
        if settings.allowed_emails:
            new_lines.append(f"ALLOWED_EMAILS={settings.allowed_emails}")

        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.info("Updated Google OAuth credentials in .env")

auth_service = AuthService()
