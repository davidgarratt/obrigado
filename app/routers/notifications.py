import logging
import secrets
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    device_name: Optional[str] = "Pixel 10 XL"

class PushUnsubscribeRequest(BaseModel):
    endpoint: str

class NotificationConfigUpdateRequest(BaseModel):
    webpush_enabled: Optional[bool] = True
    ntfy_enabled: Optional[bool] = True
    ntfy_topic: Optional[str] = None
    ntfy_server_url: Optional[str] = "https://ntfy.sh"
    notify_on_briefing: Optional[bool] = True
    notify_on_elicitation: Optional[bool] = True
    notify_on_urgent_nudge: Optional[bool] = True

class TestNotificationRequest(BaseModel):
    device_name: Optional[str] = "Pixel 10 XL"

@router.get("/config")
async def get_notification_config(request: Request):
    """Retrieve active notification channel settings, VAPID key, and subscriber devices."""
    cfg = notification_service.get_config()
    subs = notification_service.list_subscriptions()
    return {
        "success": True,
        "config": cfg,
        "subscriptions": subs,
        "vapid_public_key": notification_service.get_vapid_public_key()
    }

@router.post("/config")
async def update_notification_config(req: NotificationConfigUpdateRequest):
    """Update notification channel preferences, ntfy topic, and category toggles."""
    updated = notification_service.update_config(req.model_dump(exclude_unset=True))
    return {
        "success": True,
        "message": "Notification preferences saved successfully.",
        "config": updated
    }

@router.post("/subscribe")
async def subscribe_push(req: PushSubscribeRequest, request: Request):
    """Register a WebPush subscription from Chrome on the user's Pixel 10 XL."""
    ua = request.headers.get("user-agent", "")
    res = notification_service.add_subscription(
        endpoint=req.endpoint,
        p256dh=req.keys.p256dh,
        auth=req.keys.auth,
        device_name=req.device_name or "Pixel 10 XL",
        user_agent=ua
    )
    return res

@router.post("/unsubscribe")
async def unsubscribe_push(req: PushUnsubscribeRequest):
    """Remove a WebPush subscription."""
    notification_service.remove_subscription(req.endpoint)
    return {"success": True, "message": "Subscription removed."}

@router.post("/test")
async def send_test_notification(req: TestNotificationRequest = TestNotificationRequest()):
    """Send an immediate test notification to the user's phone across active channels."""
    res = notification_service.send_test_notification(device_hint=req.device_name or "Pixel 10 XL")
    return res

@router.post("/generate-topic")
async def generate_random_topic():
    """Generates a secure random topic name for ntfy.sh."""
    suffix = secrets.token_hex(6)
    new_topic = f"obrigado_pixel_{suffix}"
    return {"success": True, "topic": new_topic}
