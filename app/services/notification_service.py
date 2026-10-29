import os
import json
import base64
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
import pywebpush

from app.config import settings
from app.database import get_db_connection, utc_now_iso

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        self._vapid = None
        self._public_key_b64 = None
        self._private_pem = None
        self._init_vapid_keys()

    def _init_vapid_keys(self):
        """Load or automatically generate persistent VAPID keys for WebPush."""
        key_file = settings.data_dir / ".vapid_keys.json"
        
        # 1. Try loading from file
        if key_file.exists():
            try:
                data = json.loads(key_file.read_text(encoding="utf-8"))
                self._public_key_b64 = data.get("public_key")
                self._private_pem = data.get("private_pem")
                if self._private_pem and self._public_key_b64:
                    self._vapid = Vapid.from_pem(self._private_pem.encode("ascii"))
                    logger.info("Loaded persistent VAPID WebPush keys.")
                    return
            except Exception as e:
                logger.warning(f"Failed to load VAPID keys file: {e}. Generating new keypair.")

        # 2. Generate fresh keypair
        try:
            vapid = Vapid()
            vapid.generate_keys()

            # Base64url uncompressed public key for browser applicationServerKey
            raw_pub = vapid.public_key.public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint
            )
            self._public_key_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b'=').decode('ascii')

            # PEM private key
            self._private_pem = vapid.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode('ascii')

            self._vapid = vapid

            # Save to data directory
            key_file.write_text(json.dumps({
                "public_key": self._public_key_b64,
                "private_pem": self._private_pem,
                "generated_at": utc_now_iso()
            }, indent=2), encoding="utf-8")
            logger.info("Generated new persistent VAPID keypair for Android WebPush.")
        except Exception as e:
            logger.error(f"Failed to generate VAPID keys: {e}")

    def get_vapid_public_key(self) -> str:
        """Returns the public key used by the browser PushManager.subscribe()."""
        return self._public_key_b64 or ""

    def get_config(self) -> Dict[str, Any]:
        """Returns current notification channel and preference settings."""
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM notification_configs WHERE id = 'default'").fetchone()
        conn.close()

        if not row:
            return {
                "webpush_enabled": True,
                "ntfy_enabled": True,
                "ntfy_topic": "obrigado_pixel_alerts",
                "ntfy_server_url": "https://ntfy.sh",
                "notify_on_briefing": True,
                "notify_on_elicitation": True,
                "notify_on_urgent_nudge": True,
                "vapid_public_key": self.get_vapid_public_key()
            }

        d = dict(row)
        return {
            "webpush_enabled": bool(d.get("webpush_enabled", 1)),
            "ntfy_enabled": bool(d.get("ntfy_enabled", 1)),
            "ntfy_topic": d.get("ntfy_topic") or "obrigado_pixel_alerts",
            "ntfy_server_url": d.get("ntfy_server_url") or "https://ntfy.sh",
            "notify_on_briefing": bool(d.get("notify_on_briefing", 1)),
            "notify_on_elicitation": bool(d.get("notify_on_elicitation", 1)),
            "notify_on_urgent_nudge": bool(d.get("notify_on_urgent_nudge", 1)),
            "vapid_public_key": self.get_vapid_public_key()
        }

    def update_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Updates notification channel settings and preferences."""
        conn = get_db_connection()
        now = utc_now_iso()
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO notification_configs (
                    id, webpush_enabled, ntfy_enabled, ntfy_topic, ntfy_server_url,
                    notify_on_briefing, notify_on_elicitation, notify_on_urgent_nudge, updated_at
                ) VALUES (
                    'default', ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                1 if config_data.get("webpush_enabled", True) else 0,
                1 if config_data.get("ntfy_enabled", True) else 0,
                config_data.get("ntfy_topic", "obrigado_pixel_alerts").strip(),
                config_data.get("ntfy_server_url", "https://ntfy.sh").strip().rstrip("/"),
                1 if config_data.get("notify_on_briefing", True) else 0,
                1 if config_data.get("notify_on_elicitation", True) else 0,
                1 if config_data.get("notify_on_urgent_nudge", True) else 0,
                now
            ))
        conn.close()
        return self.get_config()

    def add_subscription(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        device_name: str = "Pixel 10 XL",
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """Registers a WebPush subscription from Chrome on the Pixel 10 XL."""
        conn = get_db_connection()
        now = utc_now_iso()
        sub_id = f"sub_{secrets_token()}"
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO push_subscriptions (
                    id, endpoint, p256dh, auth, device_name, user_agent, created_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sub_id, endpoint, p256dh, auth, device_name, user_agent or "", now, now))
        conn.close()
        logger.info(f"Registered push subscription for device: {device_name}")
        return {"success": True, "device_name": device_name, "subscription_id": sub_id}

    def remove_subscription(self, endpoint: str) -> bool:
        """Removes an unsubscribed or expired WebPush subscription."""
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.close()
        logger.info("Removed push subscription.")
        return True

    def list_subscriptions(self) -> List[Dict[str, Any]]:
        """Lists all registered push subscriber devices."""
        conn = get_db_connection()
        rows = conn.execute("SELECT id, device_name, user_agent, created_at, last_used_at FROM push_subscriptions ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def send_notification(
        self,
        title: str,
        body: str,
        url: str = "/",
        category: str = "general",
        priority: str = "high",
        tags: str = "robot"
    ) -> Dict[str, Any]:
        """
        Dispatches a notification across enabled channels:
        1. Native Web Push (to Chrome on Pixel 10 XL)
        2. ntfy.sh (to ntfy Android app on Pixel 10 XL)
        """
        config = self.get_config()

        # Check category preferences
        if category == "briefing" and not config["notify_on_briefing"]:
            logger.info("Skipping notification: briefing alerts disabled in preferences.")
            return {"skipped": True, "reason": "briefing_disabled"}
        if category == "elicitation" and not config["notify_on_elicitation"]:
            logger.info("Skipping notification: elicitation alerts disabled in preferences.")
            return {"skipped": True, "reason": "elicitation_disabled"}
        if category == "urgent_nudge" and not config["notify_on_urgent_nudge"]:
            logger.info("Skipping notification: urgent nudge alerts disabled in preferences.")
            return {"skipped": True, "reason": "urgent_nudge_disabled"}

        results = {
            "webpush": {"sent": 0, "failed": 0, "pruned": 0},
            "ntfy": {"sent": False, "error": None}
        }

        # 1. Native Web Push Dispatch
        if config["webpush_enabled"] and self._vapid and self._private_pem:
            conn = get_db_connection()
            subs = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()
            conn.close()

            payload = json.dumps({
                "title": title,
                "body": body,
                "icon": "/static/icons/icon-192.png",
                "badge": "/static/icons/badge-72.png",
                "tag": f"obrigado-{category}",
                "vibrate": [120, 60, 120],
                "data": {
                    "url": url,
                    "category": category,
                    "timestamp": utc_now_iso()
                },
                "actions": [
                    {"action": "open", "title": "Open Obrigado"}
                ]
            })

            vapid_claims = {
                "sub": "mailto:notifications@obrigado.local"
            }

            for sub in subs:
                sub_info = {
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh"],
                        "auth": sub["auth"]
                    }
                }
                try:
                    pywebpush.webpush(
                        subscription_info=sub_info,
                        data=payload,
                        vapid_private_key=self._vapid,
                        vapid_claims=vapid_claims,
                        ttl=86400
                    )
                    results["webpush"]["sent"] += 1
                except pywebpush.WebPushException as ex:
                    # Check if subscription has expired or been revoked (404/410)
                    response = getattr(ex, "response", None)
                    status_code = getattr(response, "status_code", None)
                    if status_code in (404, 410):
                        self.remove_subscription(sub["endpoint"])
                        results["webpush"]["pruned"] += 1
                    else:
                        logger.warning(f"WebPush failed for subscriber: {ex}")
                        results["webpush"]["failed"] += 1
                except Exception as ex:
                    logger.warning(f"WebPush error: {ex}")
                    results["webpush"]["failed"] += 1

        # 2. ntfy.sh Dispatch
        if config["ntfy_enabled"] and config["ntfy_topic"]:
            topic = config["ntfy_topic"]
            server = config["ntfy_server_url"] or "https://ntfy.sh"
            target_post_url = f"{server}/{topic}"

            # Map priority
            p_map = {"urgent": "5", "high": "4", "default": "3", "low": "2"}
            p_val = p_map.get(priority.lower(), "4")

            # Determine click URL
            app_url = settings.app_base_url or f"http://{settings.host}:{settings.port}"
            click_target = f"{app_url.rstrip('/')}{url}" if url.startswith("/") else url

            headers = {
                "Title": encode_mime_header(title),
                "Priority": p_val,
                "Tags": tags,
                "Click": click_target,
                "Actions": f"view, Open Obrigado, {click_target}"
            }

            try:
                res = requests.post(
                    target_post_url,
                    data=body.encode("utf-8"),
                    headers=headers,
                    timeout=6
                )
                if res.ok:
                    results["ntfy"]["sent"] = True
                else:
                    results["ntfy"]["error"] = f"HTTP {res.status_code}: {res.text}"
            except Exception as e:
                logger.warning(f"ntfy push delivery failed: {e}")
                results["ntfy"]["error"] = str(e)

        logger.info(f"Notification sent: '{title}' -> WebPush: {results['webpush']['sent']} sent, ntfy: {results['ntfy']['sent']}")
        return {"success": True, "results": results}

    def notify_briefing_ready(self, briefing_type: str, preview_markdown: str) -> Dict[str, Any]:
        """Notifies user when morning, evening, or leadership briefing is ready."""
        type_labels = {
            "morning": "Morning Briefing",
            "evening": "Evening Review",
            "cto": "Leadership Briefing"
        }
        name = type_labels.get(briefing_type.lower(), f"{briefing_type.capitalize()} Briefing")
        
        # Extract clean short preview from markdown
        clean_preview = preview_markdown.replace("#", "").replace("*", "").strip()
        first_line = clean_preview.split("\n")[0] if clean_preview else "Your briefing is ready to review."
        if len(first_line) > 120:
            first_line = first_line[:117] + "..."

        title = f"Obrigado · {name} Ready"
        body = first_line
        return self.send_notification(
            title=title,
            body=body,
            url="/?tab=briefing",
            category="briefing",
            priority="high",
            tags="newspaper,briefing"
        )

    def notify_elicitation(self, question: str, node_title: str) -> Dict[str, Any]:
        """Notifies user when Obrigado needs clarification on a captured item."""
        title = "Obrigado · Quick Clarification Needed"
        body = f"Regarding '{node_title}': {question}"
        if len(body) > 130:
            body = body[:127] + "..."

        return self.send_notification(
            title=title,
            body=body,
            url="/?tab=capture",
            category="elicitation",
            priority="urgent",
            tags="question,memo"
        )

    def notify_urgent_obligation(self, title: str, due_date: Optional[str] = None) -> Dict[str, Any]:
        """Notifies user of imminent Q1 deadline or high urgency obligation."""
        t = "Obrigado · Urgent Obligation Alert"
        due_str = f"due {due_date}" if due_date else "pending immediate attention"
        body = f"'{title}' is {due_str}. Tap to schedule or resolve."
        return self.send_notification(
            title=t,
            body=body,
            url="/?tab=matrix",
            category="urgent_nudge",
            priority="urgent",
            tags="warning,calendar"
        )

    def send_test_notification(self, device_hint: str = "Pixel 10 XL") -> Dict[str, Any]:
        """Sends an immediate verification ping to the user's phone."""
        title = f"Obrigado · {device_hint} Connected! 🎉"
        body = "Push notifications are active! Morning briefings, elicitations, and urgent nudges will appear on this device."
        return self.send_notification(
            title=title,
            body=body,
            url="/?tab=settings",
            category="general",
            priority="high",
            tags="tada,smartphone"
        )

def secrets_token() -> str:
    import secrets
    return secrets.token_hex(8)

def encode_mime_header(text: str) -> str:
    """MIME encode non-ascii headers so HTTP client doesn't raise latin-1 encoding errors."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"=?UTF-8?B?{b64}?="

notification_service = NotificationService()
