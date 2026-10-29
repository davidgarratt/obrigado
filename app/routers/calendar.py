from typing import Optional
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel

from app.services.calendar_service import calendar_service
from app.services.graph_service import graph_service
from app.routers.auth import get_oauth_base_url

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

class AuthCodeRequest(BaseModel):
    code: str
    redirect_uri: str

class SyncNodeRequest(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None

@router.get("/status")
async def get_calendar_status():
    is_conf = calendar_service.is_configured()
    is_auth = calendar_service.is_authenticated()
    events_today = calendar_service.get_events_for_date()
    return {
        "configured": is_conf,
        "authenticated": is_auth,
        "mode": "live_google_calendar" if is_auth else "staged_local",
        "events_count_today": len(events_today),
        "help_text": "Active and synced with Google Calendar" if is_auth else "Operating in local staging mode. Add credentials.json to enable live 2-way Google Calendar sync."
    }

@router.get("/events")
async def get_events(date: Optional[str] = None):
    return calendar_service.get_events_for_date(target_date_str=date)

@router.post("/sync-node/{node_id}")
async def sync_node_to_calendar(node_id: str, req: SyncNodeRequest):
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    start_t = req.start_time or node["scheduled_start"] or node["due_date"]
    if not start_t:
        raise HTTPException(status_code=400, detail="Cannot schedule node without a scheduled start time or due date.")

    res = calendar_service.add_event(
        node_id=node_id,
        title=node["title"],
        start_time_iso=start_t,
        end_time_iso=req.end_time or node["scheduled_end"],
        description=node["description"] or "",
        category=node["category"]
    )
    return res

@router.get("/export-ics/{node_id}")
async def export_node_ics(node_id: str):
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")

    start = node["scheduled_start"] or node["due_date"] or "2026-10-25T10:00:00"
    end = node["scheduled_end"] or start
    ics_text = calendar_service.generate_ics(
        title=node["title"],
        start_iso=start,
        end_iso=end,
        description=node["description"] or ""
    )

    filename = f"{node['title'][:20].replace(' ', '_')}.ics"
    return Response(
        content=ics_text,
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/auth-url")
async def get_auth_url(request: Request):
    # Construct redirect URI using smart base URL (respects APP_BASE_URL and localhost normalization)
    base_url = get_oauth_base_url(request)
    redirect_uri = f"{base_url}/api/calendar/oauth-callback"
    url = calendar_service.get_auth_url(redirect_uri)
    if not url:
        return {
            "error": "Google client credentials file (credentials.json) not found in data/ directory.",
            "instructions": "Download OAuth 2.0 Client credentials from Google Cloud Console as credentials.json and place in data/credentials.json"
        }
    return {"auth_url": url, "redirect_uri": redirect_uri}

@router.get("/oauth-callback")
async def google_oauth_callback(code: str, request: Request):
    """Handles Google OAuth 2.0 authorization code redirect."""
    base_url = get_oauth_base_url(request)
    redirect_uri = f"{base_url}/api/calendar/oauth-callback"
    success = calendar_service.complete_auth(code, redirect_uri)
    from fastapi.responses import RedirectResponse
    if success:
        return RedirectResponse(url="/?calendar_linked=true")
    return RedirectResponse(url="/?calendar_error=true")

@router.post("/complete-auth")
async def complete_auth(req: AuthCodeRequest):
    success = calendar_service.complete_auth(req.code, req.redirect_uri)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to authenticate with Google Calendar.")
    return {"success": True, "message": "Successfully linked Google Calendar!"}
