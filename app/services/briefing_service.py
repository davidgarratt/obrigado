import uuid
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.database import get_db_connection, utc_now_iso
from app.services.gemini_service import gemini_service
from app.services.calendar_service import calendar_service
from app.services.graph_service import graph_service
from app.services.crypto_service import crypto_service
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_CONFIGS = {
    "morning": {
        "title": "Morning Kickoff (Start-of-Day)",
        "tone_directive": "Crisp, encouraging, realistic, zero fluff. Executive chief-of-staff AI.",
        "custom_instructions": "",
        "default_instructions": """1. Executive Tone: Crisp, encouraging, realistic, zero fluff.
2. Structure:
   - ☀️ **Today's Horizon**: Quick 1-2 sentence high-level orientation.
   - 📅 **Google Calendar Commitments**: Chronological list of today's fixed meetings & calendar events.
   - 🔥 **Top 3 Must-Win Obligations (Eisenhower Q1/Q2)**: High-leverage items to move forward today. Note which project each belongs to.
   - 👥 **People & Stakeholders to Remember**: Highlight anyone you are meeting or following up with today, including their role, organization, and key memory facts/preferences.
   - ⏳ **Waiting-On & Follow-ups**: Mention if someone is blocking a task and needs a quick poke today.
   - ❓ **Quick Record Clarifications**: If there are pending elicitations, ask 1 high-priority question to lock down a deadline or next step.
   - 🎯 **Suggested Day Architecture**: Propose a realistic focus block flow around calendar events.
3. Constraints: Format in clean Markdown with emojis and bold headers. Keep it to under 350 words.""",
        "default_full_template": """You are the executive chief-of-staff AI for Obrigado.
Generate the START-OF-DAY (Morning Kickoff) briefing for the user.

CONTEXT:
{context_json}

GUIDELINES FOR MORNING BRIEFING:
1. Executive Tone: Crisp, encouraging, realistic, zero fluff.
2. Structure:
   - ☀️ **Today's Horizon**: Quick 1-2 sentence high-level orientation.
   - 📅 **Google Calendar Commitments**: Chronological list of today's fixed meetings & calendar events.
   - 🔥 **Top 3 Must-Win Obligations (Eisenhower Q1/Q2)**: The high-leverage things to move forward today. Note which project each belongs to.
   - 👥 **People & Stakeholders to Remember**: Highlight anyone you are meeting or following up with today, including their role, organization, and key memory facts/preferences (so the user is completely primed and never forgets who they are).
   - ⏳ **Waiting-On & Follow-ups**: Mention if someone is blocking a task and needs a quick poke today.
   - ❓ **Quick Record Clarifications**: If there are pending elicitations, ask 1 high-priority question to lock down a deadline or next step.
   - 🎯 **Suggested Day Architecture**: Propose a realistic focus block flow around calendar events.
Format in clean Markdown with emojis and bold headers. Keep it to under 350 words."""
    },
    "cto": {
        "title": "Leadership Briefing (1-on-1 Executive Update)",
        "tone_directive": "Very brief, crisp, high-level, and strategic. Zero task-level minutiae or tactical weeds. Leadership cares about strategic momentum, workload bandwidth, and critical decisions or blockers.",
        "custom_instructions": "",
        "default_instructions": """1. Executive Tone: Very brief, crisp, high-level, and strategic. Zero task-level minutiae or tactical weeds.
2. Mandatory Structure (use these exact bold section titles):
   - 🎯 **Executive Snapshot**: 1-2 punchy sentences summarizing overall operational posture, primary focus allocation, and runway.
   - 🏆 **Recent Wins & Deliverables**: 2-3 concise bullet points highlighting key tangible wins, shipped milestones, completed POCs, or closed loops.
   - ⚡ **Current Workload & Strategic Focus**: High-level summary of active initiatives and commitment distribution. Group by strategic umbrella.
   - ❓ **Decisions & Steer Needed from Leadership**: Specific decisions, executive sign-offs, priority arbitrations, or strategic advice needed from leadership to unblock progress. If none, write "No critical blockers or decisions needed from leadership at this time."
3. Constraints: Very brief (< 250 words total). Format in clean Markdown with bullet points. Written so the user can speak directly to leadership or paste into a 1-on-1 doc.""",
        "default_full_template": """You are the executive chief-of-staff AI for Obrigado.
Generate an ON-DEMAND, HIGH-LEVEL EXECUTIVE BRIEFING prepared specifically for the user's 1-on-1 update with executive leadership.

CONTEXT:
{context_json}

CRITICAL GUIDELINES FOR LEADERSHIP BRIEFING:
1. Executive Tone: Very brief, crisp, high-level, and strategic. Zero task-level minutiae or tactical weeds. Leadership cares about strategic momentum, workload bandwidth, and critical decisions or blockers.
2. Mandatory Structure (use these exact bold section titles):
   - 🎯 **Executive Snapshot**: 1-2 punchy sentences summarizing overall operational posture, primary focus allocation, and runway.
   - 🏆 **Recent Wins & Deliverables**: 2-3 concise bullet points highlighting key tangible wins, shipped milestones, completed POCs, or closed loops.
   - ⚡ **Current Workload & Strategic Focus**: High-level summary of active initiatives and commitment distribution. Group by strategic umbrella.
   - ❓ **Decisions & Steer Needed from Leadership**: Specific decisions, executive sign-offs, priority arbitrations, or strategic advice needed from leadership to unblock progress. If none, write "No critical blockers or decisions needed from leadership at this time."
3. Constraints: Very brief (under 250 words total). Clean, executive-ready Markdown with bullet points. Written so user can speak directly to leadership or paste into a 1-on-1 doc."""
    },
    "evening": {
        "title": "Evening Debrief (End-of-Day)",
        "tone_directive": "Calming, cognitive-offloading, reassuring. Give the user peace of mind so they can disconnect.",
        "custom_instructions": "",
        "default_instructions": """1. Tone: Calming, cognitive-offloading, reassuring. Give the user peace of mind so they can disconnect.
2. Structure:
   - 🌙 **Evening Debrief**: Brief reflection on today's progress.
   - ✅ **Wins & Progress Completed Today**: Highlight what got knocked out.
   - 🔄 **Carried-Over / Overdue Items**: Gentle, shame-free assessment. What needs rollover to tomorrow?
   - 👥 **Relationship Check-in**: 1 quick question about people interacted with today.
   - 🌅 **Tomorrow's Runway**: The single most important priority lined up for tomorrow morning.
3. Constraints: Format in clean Markdown with emojis and bold headers. Keep it under 300 words.""",
        "default_full_template": """You are the executive chief-of-staff AI for Obrigado.
Generate the END-OF-DAY (Evening Debrief & Reflection) summary for the user.

CONTEXT:
{context_json}

GUIDELINES FOR EVENING BRIEFING:
1. Tone: Calming, cognitive-offloading, reassuring. Give the user peace of mind so they can disconnect.
2. Structure:
   - 🌙 **Evening Debrief**: Brief reflection on today's progress.
   - ✅ **Wins & Progress Completed Today**: Highlight what got knocked out.
   - 🔄 **Carried-Over / Overdue Items**: Gentle, shame-free assessment. What needs rollover to tomorrow?
   - 👥 **Relationship Check-in**: 1 quick question about people interacted with today.
   - 🌅 **Tomorrow's Runway**: The single most important priority lined up for tomorrow morning.
Format in clean Markdown with emojis and bold headers. Keep it under 300 words."""
    },
    "weekly": {
        "title": "Weekly Executive Review (Activity & Progress)",
        "tone_directive": "Direct, grounded, pragmatic, and candid. Strictly zero sales jargon, corporate buzzwords, or marketing fluff. Speak plainly about concrete engineering, operational facts, blockers, and decisions.",
        "custom_instructions": "",
        "default_instructions": """1. Tone & Persona:
   - Direct, grounded, pragmatic, and candid. Executive chief-of-staff AI.
   - Strictly avoid all sales talk, corporate buzzwords, sycophancy, or empty consultant-speak (e.g. no "synergy", "value proposition", "paradigm", "game-changing", "drive alignment", "move the needle", "circle back", "unpack").
   - Tell the unvarnished operational story: what was built, what was shipped, what moved, what stalled, and why.
2. Structure for Executive Review (use these exact bold headers):
   - 🎯 **Weekly Operational Snapshot**: 2-3 direct sentences summarizing the week's output, velocity, focus allocation, and runway.
   - 📦 **Delivered & Closed Loops**: Concrete deliverables, decisions, and tasks finished over the past 7 days. State facts and results clearly without hyperbole.
   - ⚙️ **Active Workstreams & Progress**: Pragmatic summary of ongoing projects and tasks updated this week. Include real operational status and percent progress.
   - 🚧 **Friction Points, Stalls & Dependencies**: Unvarnished look at what's stuck, overdue, or waiting on external people. Explain where the friction is.
   - 🧭 **Priorities for Next Week**: Top 3 high-impact focus areas to execute next week to keep the runway clear.
3. Constraints: Format in clean Markdown with bullet points. Keep it to approximately 350-450 words.""",
        "default_full_template": """You are the executive chief-of-staff AI for Obrigado.
Generate the WEEKLY EXECUTIVE REVIEW summarizing the past week's operational activity, accomplishments, and blockers for executive review.

CONTEXT:
{context_json}

CRITICAL GUIDELINES FOR WEEKLY EXECUTIVE REVIEW:
1. Grounded & Direct Tone: Strictly avoid sales talk, corporate buzzwords, marketing puffery, or generic corporate speak. Write in plain, clear, intelligent English with zero fluff.
2. Structure (use these exact bold section titles):
   - 🎯 **Weekly Operational Snapshot**: 2-3 direct sentences summarizing the week's output, velocity, and focus allocation.
   - 📦 **Delivered & Closed Loops**: Concrete deliverables, decisions, and obligations completed over the week.
   - ⚙️ **Active Workstreams & Progress**: Factual status of projects and key tasks in flight, with progress and milestones reached.
   - 🚧 **Friction Points, Stalls & Dependencies**: Real assessment of what is blocked, overdue, or bottlenecked on third parties.
   - 🧭 **Priorities for Next Week**: Clear, high-leverage focus areas for the upcoming week.
3. Constraints: Format in clean Markdown with bullet points. Approximately 350-450 words."""
    }
}

class BriefingService:
    def __init__(self):
        pass

    def generate_briefing(self, summary_type: str = "morning", target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Synthesizes calendar events, graph obligations, projects, and generates
        an intelligent start-of-day or end-of-day summary using Gemini.
        """
        now = datetime.now()
        date_str = target_date or now.strftime("%Y-%m-%d")
        summary_type = summary_type.lower()
        if summary_type not in ("morning", "evening", "cto", "weekly"):
            summary_type = "morning"

        week_ago_dt = now - timedelta(days=7)
        week_ago_iso = (now.astimezone(timezone.utc) - timedelta(days=7)).isoformat()
        week_ago_date = week_ago_dt.strftime("%Y-%m-%d")

        # 1. Fetch Calendar Events
        if summary_type == "weekly":
            # For weekly review, pull calendar events across the last 7 days + next 3 days
            calendar_events = []
            for i in range(-7, 4):
                d = (now + timedelta(days=i)).strftime("%Y-%m-%d")
                calendar_events.extend(calendar_service.get_events_for_date(d))
            # Deduplicate by id
            seen_evs = set()
            unique_events = []
            for ev in calendar_events:
                if ev["id"] not in seen_evs:
                    seen_evs.add(ev["id"])
                    unique_events.append(ev)
            calendar_events = unique_events
        else:
            calendar_events = calendar_service.get_events_for_date(date_str)

        # 2. Fetch Graph Obligations
        all_nodes = graph_service.get_all_nodes()
        all_edges = graph_service.get_all_edges()

        obligations = [n for n in all_nodes if n["node_type"] == "obligation"]
        projects = [n for n in all_nodes if n["node_type"] == "project" and n["status"] in ("pending", "in_progress")]

        # Filter by Eisenhower quadrants
        q1_items = [o for o in obligations if o["eisenhower_quadrant"] == "Q1_DO_FIRST" and o["status"] in ("pending", "in_progress")]
        q2_items = [o for o in obligations if o["eisenhower_quadrant"] == "Q2_SCHEDULE" and o["status"] in ("pending", "in_progress")]

        # Sort Q1 and Q2 by urgency and importance
        q1_items.sort(key=lambda x: (x["urgency_score"] + x["importance_score"]), reverse=True)
        q2_items.sort(key=lambda x: (x["importance_score"]), reverse=True)

        # Waiting-on items
        waiting_on = [o for o in obligations if o["status"] == "waiting_on"]

        # Completed wins: for Weekly Review and CTO briefing, grab items completed in the past 7 days (or recent wins); for daily, today's
        if summary_type in ("cto", "weekly"):
            completed_wins = [
                o for o in obligations 
                if o["status"] == "completed" and (
                    (o.get("completed_at") or o.get("updated_at") or "") >= week_ago_iso or
                    (o.get("completed_at") or o.get("updated_at") or "")[:10] >= week_ago_date
                )
            ]
            completed_wins.sort(key=lambda x: x.get("completed_at") or x.get("updated_at") or "", reverse=True)
            if len(completed_wins) < 4:
                all_completed = [o for o in obligations if o["status"] == "completed"]
                all_completed.sort(key=lambda x: x.get("completed_at") or x.get("updated_at") or "", reverse=True)
                completed_wins = all_completed[:8]
            wins_to_report = completed_wins
        else:
            wins_to_report = [
                o for o in obligations 
                if o["status"] == "completed" and (o.get("completed_at") or "").startswith(date_str)
            ]

        # Overdue items
        overdue_items = []
        for o in obligations:
            if o["status"] in ("pending", "in_progress") and o.get("due_date"):
                try:
                    due_date_clean = o["due_date"].split("T")[0]
                    if due_date_clean < date_str:
                        overdue_items.append(o)
                except Exception:
                    pass

        # Activity notes & progress updates logged across the week (for weekly review)
        weekly_activity_notes = []
        if summary_type == "weekly":
            conn = get_db_connection()
            raw_notes_rows = conn.execute(
                "SELECT content, created_at FROM raw_notes WHERE created_at >= ? ORDER BY created_at DESC LIMIT 20",
                (week_ago_iso,)
            ).fetchall()
            for r in raw_notes_rows:
                dec = crypto_service.decrypt(r["content"])
                if dec:
                    weekly_activity_notes.append({
                        "date": r["created_at"].split("T")[0] if "T" in r["created_at"] else r["created_at"],
                        "note": dec[:250]
                    })
            conn.close()

            # Also pull progress updates recorded on tasks during the week
            for o in obligations:
                meta = o.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                p_updates = meta.get("progress_updates", [])
                for u in p_updates:
                    ts = u.get("timestamp", "")
                    if ts >= week_ago_iso or ts[:10] >= week_ago_date:
                        weekly_activity_notes.append({
                            "date": ts.split("T")[0] if "T" in ts else ts,
                            "task": o.get("title", ""),
                            "update": u.get("update_text", ""),
                            "changes": u.get("changes_summary", "")
                        })

        # 3. Fetch people involved in today's commitments & pending elicitations
        conn = get_db_connection()
        pending_elicitations = [
            {
                "task_title": crypto_service.decrypt(r["task_title"]) or "",
                "question": crypto_service.decrypt(r["question"]) or ""
            }
            for r in conn.execute(
                """
                SELECT e.question, n.title as task_title 
                FROM elicitations e 
                JOIN nodes n ON e.node_id = n.id 
                WHERE e.status = 'pending' 
                ORDER BY e.created_at DESC LIMIT 4
                """
            ).fetchall()
        ]

        active_task_ids = [item["id"] for item in (q1_items + q2_items + waiting_on)[:10]]
        people_involved = []
        if active_task_ids:
            placeholders = ",".join("?" * len(active_task_ids))
            people_rows = conn.execute(
                f"""
                SELECT DISTINCT p.id, p.title as name, p.description, p.metadata_json
                FROM edges ed
                JOIN nodes p ON ed.target_id = p.id AND p.node_type = 'person'
                WHERE ed.source_id IN ({placeholders})
                LIMIT 6
                """,
                active_task_ids
            ).fetchall()
            for prow in people_rows:
                pid = prow["id"]
                p_name = crypto_service.decrypt(prow["name"]) or ""
                p_desc = crypto_service.decrypt(prow["description"]) or ""
                meta_raw = crypto_service.decrypt(prow["metadata_json"]) or "{}"
                try:
                    meta = json.loads(meta_raw)
                except Exception:
                    meta = {}

                mems = [
                    crypto_service.decrypt(m["memory_fact"]) or "" for m in conn.execute(
                        "SELECT memory_fact FROM person_memories WHERE person_node_id = ? ORDER BY created_at DESC LIMIT 2",
                        (pid,)
                    ).fetchall()
                ]
                people_involved.append({
                    "name": p_name,
                    "role": meta.get("role_or_title") or p_desc,
                    "organization": meta.get("organization") or "",
                    "relationship": meta.get("relationship_type") or "colleague",
                    "key_memories": mems
                })
        conn.close()

        # 4. Call Gemini to synthesize
        current_time_str = now.astimezone().isoformat()
        prompt_config = self.get_prompt_config(summary_type)
        markdown_content = gemini_service.generate_daily_briefing(
            summary_type=summary_type,
            current_time_str=current_time_str,
            calendar_events=calendar_events,
            q1_obligations=q1_items[:5],
            q2_obligations=q2_items[:5],
            waiting_on_items=waiting_on[:5],
            completed_today=wins_to_report,
            overdue_items=overdue_items[:5],
            active_projects=projects[:6],
            people_involved=people_involved,
            pending_elicitations=pending_elicitations,
            prompt_config=prompt_config,
            weekly_activity_notes=weekly_activity_notes
        )

        metrics = {
            "date": date_str,
            "calendar_events_count": len(calendar_events),
            "q1_count": len(q1_items),
            "q2_count": len(q2_items),
            "waiting_count": len(waiting_on),
            "completed_today_count": len(wins_to_report),
            "overdue_count": len(overdue_items),
            "active_projects_count": len(projects),
            "weekly_activity_count": len(weekly_activity_notes)
        }

        # 4. Save to Database (Encrypted at rest)
        summary_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        enc_markdown = crypto_service.encrypt(markdown_content)
        enc_metrics = crypto_service.encrypt(json.dumps(metrics))
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO daily_summaries (id, summary_date, summary_type, content_markdown, metrics_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (summary_id, date_str, summary_type, enc_markdown, enc_metrics, created_at)
            )
        conn.close()

        return {
            "id": summary_id,
            "summary_date": date_str,
            "summary_type": summary_type,
            "content_markdown": markdown_content,
            "metrics": metrics,
            "created_at": created_at
        }

    def get_prompt_config(self, summary_type: str) -> Dict[str, Any]:
        summary_type = summary_type.lower()
        default_cfg = DEFAULT_PROMPT_CONFIGS.get(summary_type, DEFAULT_PROMPT_CONFIGS["morning"])

        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM briefing_prompt_configs WHERE briefing_type = ?",
                (summary_type,)
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        finally:
            conn.close()

        if row:
            r = dict(row)
            custom_instructions = crypto_service.decrypt(r.get("custom_instructions")) or ""
            full_template = crypto_service.decrypt(r.get("full_template")) if r.get("full_template") else None
            return {
                "briefing_type": summary_type,
                "title": default_cfg["title"],
                "tone_directive": r.get("tone_directive") or default_cfg["tone_directive"],
                "custom_instructions": custom_instructions,
                "full_template": full_template,
                "is_customized": bool(r.get("tone_directive") or custom_instructions or full_template),
                "default_tone": default_cfg["tone_directive"],
                "default_instructions": default_cfg["default_instructions"],
                "default_full_template": default_cfg["default_full_template"],
                "updated_at": r.get("updated_at")
            }
        else:
            return {
                "briefing_type": summary_type,
                "title": default_cfg["title"],
                "tone_directive": default_cfg["tone_directive"],
                "custom_instructions": "",
                "full_template": None,
                "is_customized": False,
                "default_tone": default_cfg["tone_directive"],
                "default_instructions": default_cfg["default_instructions"],
                "default_full_template": default_cfg["default_full_template"],
                "updated_at": None
            }

    def get_all_prompt_configs(self) -> Dict[str, Any]:
        return {
            t: self.get_prompt_config(t)
            for t in ("morning", "evening", "cto", "weekly")
        }

    def update_prompt_config(
        self,
        summary_type: str,
        tone_directive: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        full_template: Optional[str] = None
    ) -> Dict[str, Any]:
        summary_type = summary_type.lower()
        if summary_type not in ("morning", "evening", "cto", "weekly"):
            raise ValueError(f"Unknown briefing type: {summary_type}")

        conn = get_db_connection()
        now_str = utc_now_iso()
        enc_custom = crypto_service.encrypt(custom_instructions or "")
        enc_template = crypto_service.encrypt(full_template) if full_template and full_template.strip() else None
        with conn:
            conn.execute(
                """
                INSERT INTO briefing_prompt_configs (briefing_type, tone_directive, custom_instructions, full_template, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(briefing_type) DO UPDATE SET
                    tone_directive = excluded.tone_directive,
                    custom_instructions = excluded.custom_instructions,
                    full_template = excluded.full_template,
                    updated_at = excluded.updated_at
                """,
                (summary_type, tone_directive or "", enc_custom, enc_template, now_str)
            )
        conn.close()
        return self.get_prompt_config(summary_type)

    def reset_prompt_config(self, summary_type: str) -> Dict[str, Any]:
        summary_type = summary_type.lower()
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM briefing_prompt_configs WHERE briefing_type = ?", (summary_type,))
        conn.close()
        return self.get_prompt_config(summary_type)

    def get_latest_briefing(self, summary_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        query = "SELECT * FROM daily_summaries WHERE 1=1"
        params = []
        if summary_type:
            query += " AND summary_type = ?"
            params.append(summary_type)
        query += " ORDER BY created_at DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["content_markdown"] = crypto_service.decrypt(d.get("content_markdown")) or ""
        metrics_raw = crypto_service.decrypt(d.get("metrics_json")) or "{}"
        try:
            d["metrics"] = json.loads(metrics_raw)
        except Exception:
            d["metrics"] = {}
        return d

    def get_briefing_history(self, limit: int = 15) -> list:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM daily_summaries ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            d["content_markdown"] = crypto_service.decrypt(d.get("content_markdown")) or ""
            metrics_raw = crypto_service.decrypt(d.get("metrics_json")) or "{}"
            try:
                d["metrics"] = json.loads(metrics_raw)
            except Exception:
                d["metrics"] = {}
            results.append(d)
        return results

briefing_service = BriefingService()
