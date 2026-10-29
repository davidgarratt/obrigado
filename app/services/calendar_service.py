import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import settings
from app.database import get_db_connection, utc_now_iso

logger = logging.getLogger(__name__)

# Google Calendar API Scopes
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

class GoogleCalendarService:
    def __init__(self):
        self.credentials_file = Path(settings.google_client_secrets_file)
        self.token_file = Path(settings.google_token_file)
        self._service = None

    def is_configured(self) -> bool:
        """Check if OAuth client secrets file exists."""
        return self.credentials_file.exists()

    def is_authenticated(self) -> bool:
        """Check if active user token exists and is valid."""
        if not self.token_file.exists():
            return False
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            if creds and creds.valid:
                return True
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self.token_file, 'w') as f:
                    f.write(creds.to_json())
                return True
        except Exception as e:
            logger.warning(f"Error checking calendar auth: {e}")
        return False

    def get_service(self):
        """Build Google Calendar Resource if authenticated."""
        if self._service:
            return self._service
        if not self.is_authenticated():
            return None
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
            self._service = build('calendar', 'v3', credentials=creds)
            return self._service
        except Exception as e:
            logger.error(f"Failed to create Google Calendar service: {e}")
            return None

    def get_auth_url(self, redirect_uri: str) -> Optional[str]:
        """Generate Google OAuth authorization URL."""
        if not self.is_configured():
            return None
        try:
            from google_auth_oauthlib.flow import Flow
            flow = Flow.from_client_secrets_file(
                str(self.credentials_file),
                scopes=SCOPES,
                redirect_uri=redirect_uri
            )
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            return auth_url
        except Exception as e:
            logger.error(f"Error generating auth URL: {e}")
            return None

    def complete_auth(self, code: str, redirect_uri: str) -> bool:
        """Exchange authorization code for tokens."""
        if not self.is_configured():
            return False
        try:
            from google_auth_oauthlib.flow import Flow
            flow = Flow.from_client_secrets_file(
                str(self.credentials_file),
                scopes=SCOPES,
                redirect_uri=redirect_uri
            )
            flow.fetch_token(code=code)
            creds = flow.credentials
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())
            self._service = None
            return True
        except Exception as e:
            logger.error(f"Error completing OAuth flow: {e}")
            return False

    def add_event(
        self,
        node_id: str,
        title: str,
        start_time_iso: str,
        end_time_iso: Optional[str] = None,
        description: str = "",
        category: str = "work"
    ) -> Dict[str, Any]:
        """
        Create event in Google Calendar if authenticated, or stage in local DB if offline/unauthenticated.
        """
        service = self.get_service()

        # Format start & end
        clean_start = start_time_iso
        if "T" not in clean_start:
            clean_start = f"{clean_start}T10:00:00"
        
        if not end_time_iso:
            try:
                st = datetime.fromisoformat(clean_start)
                end_time_iso = (st + timedelta(minutes=45)).isoformat()
            except Exception:
                end_time_iso = clean_start

        if service:
            try:
                event_body = {
                    'summary': f"[{category.upper()}] {title}",
                    'description': f"{description}\n\nManaged by Obrigado",
                    'start': {
                        'dateTime': clean_start if '+' in clean_start or 'Z' in clean_start else f"{clean_start}+01:00",
                        'timeZone': settings.user_timezone,
                    },
                    'end': {
                        'dateTime': end_time_iso if '+' in end_time_iso or 'Z' in end_time_iso else f"{end_time_iso}+01:00",
                        'timeZone': settings.user_timezone,
                    },
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'popup', 'minutes': 15},
                            {'method': 'email', 'minutes': 60},
                        ],
                    },
                }

                created = service.events().insert(calendarId='primary', body=event_body).execute()
                event_id = created.get('id')
                html_link = created.get('htmlLink')

                # Update node in SQLite
                conn = get_db_connection()
                with conn:
                    conn.execute(
                        """
                        UPDATE nodes 
                        SET calendar_event_id = ?, calendar_sync_status = 'synced',
                            scheduled_start = ?, scheduled_end = ?
                        WHERE id = ?
                        """,
                        (event_id, clean_start, end_time_iso, node_id)
                    )
                conn.close()

                return {
                    "success": True,
                    "event_id": event_id,
                    "html_link": html_link,
                    "status": "synced",
                    "mode": "google_api"
                }

            except Exception as e:
                logger.error(f"Google Calendar API insert failed: {e}")

        # Local Staging Mode (Works without credentials or when offline)
        local_event_id = f"local_{node_id[:8]}"
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                UPDATE nodes 
                SET calendar_event_id = ?, calendar_sync_status = 'staged_local',
                    scheduled_start = ?, scheduled_end = ?
                WHERE id = ?
                """,
                (local_event_id, clean_start, end_time_iso, node_id)
            )
        conn.close()

        return {
            "success": True,
            "event_id": local_event_id,
            "status": "staged_local",
            "mode": "local_storage",
            "message": "Event scheduled in Obrigado (ready to sync with Google Calendar once authorized)"
        }

    def get_events_for_date(self, target_date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get calendar events for a specific date (defaults to today).
        Combines Google Calendar live events (if authenticated) and local staged events.
        """
        target = target_date_str or datetime.now().strftime("%Y-%m-%d")
        events: List[Dict[str, Any]] = []

        service = self.get_service()
        if service:
            try:
                time_min = f"{target}T00:00:00Z"
                time_max = f"{target}T23:59:59Z"
                events_result = service.events().list(
                    calendarId='primary',
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                items = events_result.get('items', [])
                for item in items:
                    start = item['start'].get('dateTime', item['start'].get('date'))
                    end = item['end'].get('dateTime', item['end'].get('date'))
                    events.append({
                        "id": item['id'],
                        "title": item.get('summary', 'Untitled Event'),
                        "start_time": start,
                        "end_time": end,
                        "html_link": item.get('htmlLink', ''),
                        "source": "google_calendar"
                    })
            except Exception as e:
                logger.warning(f"Error fetching Google Calendar events: {e}")

        # Also pull scheduled nodes from local database
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT id, title, scheduled_start, scheduled_end, category, calendar_sync_status
            FROM nodes 
            WHERE (scheduled_start LIKE ? OR due_date LIKE ?) 
              AND status != 'cancelled'
            """,
            (f"{target}%", f"{target}%")
        ).fetchall()
        conn.close()

        for r in rows:
            # Avoid duplicate if Google event ID matches
            if not any(ev["id"] == r["id"] for ev in events):
                events.append({
                    "id": r["id"],
                    "title": r["title"],
                    "start_time": r["scheduled_start"] or f"{target}T10:00:00",
                    "end_time": r["scheduled_end"] or f"{target}T11:00:00",
                    "category": r["category"],
                    "source": "mindgraph_local",
                    "sync_status": r["calendar_sync_status"]
                })

        return events

    def generate_ics(self, title: str, start_iso: str, end_iso: str, description: str = "") -> str:
        """Generate standard iCalendar (.ics) string for direct calendar import."""
        def format_ics_dt(iso_str: str) -> str:
            clean = iso_str.replace("-", "").replace(":", "").split(".")[0].split("+")[0]
            if "T" not in clean:
                clean = clean + "T100000"
            return clean + "Z"

        dt_start = format_ics_dt(start_iso)
        dt_end = format_ics_dt(end_iso)
        now_dt = format_ics_dt(datetime.now(timezone.utc).isoformat())

        return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Obrigado//EN
CALSCALE:GREGORIAN
BEGIN:VEVENT
UID:{dt_start}-{abs(hash(title))}@obrigado.local
DTSTAMP:{now_dt}
DTSTART:{dt_start}
DTEND:{dt_end}
SUMMARY:{title}
DESCRIPTION:{description}
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""

calendar_service = GoogleCalendarService()
