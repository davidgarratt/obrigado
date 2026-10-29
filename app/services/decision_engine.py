import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from app.database import get_db_connection, utc_now_iso
from app.services.graph_service import graph_service
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

class DecisionEngine:
    """
    Decision-theoretic model and reasoning engine for Obrigado.
    Implements:
    - Multi-Attribute Utility Theory (MAUT) for Eisenhower Prioritization
    - Graph-Aware Urgency & Importance propagation (downstream fan-out impact)
    - Action Triage & Calendar Allocation Model
    - Proactive Anomaly & Cognitive Nudge generation
    """

    def __init__(self):
        pass

    def evaluate_obligation_priority(
        self,
        base_urgency: float,
        base_importance: float,
        due_date: Optional[str] = None,
        dependent_count: int = 0,
        category: str = "work",
        energy_required: str = "medium"
    ) -> Dict[str, Any]:
        """
        Refines Urgency and Importance using graph fan-out and temporal decay.
        """
        now = datetime.now(timezone.utc)
        calculated_urgency = base_urgency
        calculated_importance = base_importance

        # 1. Temporal urgency adjustment
        time_factor_applied = False
        hours_remaining = None
        if due_date:
            try:
                # Parse ISO date or datetime
                clean_due = due_date.replace("Z", "+00:00")
                if "T" in clean_due:
                    dt_due = datetime.fromisoformat(clean_due)
                else:
                    dt_due = datetime.fromisoformat(clean_due + "T23:59:59+00:00")
                
                if dt_due.tzinfo is None:
                    dt_due = dt_due.replace(tzinfo=timezone.utc)

                delta = (dt_due - now).total_seconds() / 3600.0 # in hours
                hours_remaining = round(delta, 1)

                if delta <= 0:
                    # Overdue! Max urgency
                    calculated_urgency = 1.0
                    time_factor_applied = True
                elif delta <= 24:
                    # Due within 24h
                    calculated_urgency = max(calculated_urgency, 0.95)
                    time_factor_applied = True
                elif delta <= 48:
                    # Due within 48h
                    calculated_urgency = max(calculated_urgency, 0.8)
                    time_factor_applied = True
                elif delta <= 72:
                    calculated_urgency = max(calculated_urgency, 0.65)
                    time_factor_applied = True
            except Exception as e:
                logger.debug(f"Could not parse due date '{due_date}': {e}")

        # 2. Graph fan-out adjustment (if others depend on this obligation, importance scales up!)
        graph_boost = 0.0
        if dependent_count > 0:
            graph_boost = min(0.35, 0.12 * dependent_count)
            calculated_importance = min(1.0, calculated_importance + graph_boost)

        # 3. Eisenhower quadrant determination
        if calculated_urgency >= 0.5 and calculated_importance >= 0.5:
            quadrant = "Q1_DO_FIRST"
        elif calculated_urgency < 0.5 and calculated_importance >= 0.5:
            quadrant = "Q2_SCHEDULE"
        elif calculated_urgency >= 0.5 and calculated_importance < 0.5:
            quadrant = "Q3_DELEGATE"
        else:
            quadrant = "Q4_DONT_DO"

        # Overall utility score for ordering (weighted sum)
        utility_score = (0.55 * calculated_urgency) + (0.45 * calculated_importance)

        return {
            "urgency_score": round(calculated_urgency, 2),
            "importance_score": round(calculated_importance, 2),
            "eisenhower_quadrant": quadrant,
            "utility_score": round(utility_score, 2),
            "hours_remaining": hours_remaining,
            "graph_boost_applied": graph_boost > 0,
            "time_factor_applied": time_factor_applied
        }

    def decide_calendar_action(
        self,
        node_title: str,
        node_type: str,
        is_calendar_candidate: bool,
        calendar_start: Optional[str] = None,
        calendar_end: Optional[str] = None,
        due_date: Optional[str] = None,
        estimated_minutes: int = 30,
        quadrant: str = "Q2_SCHEDULE",
        urgency: float = 0.5
    ) -> Dict[str, Any]:
        """
        Decision Model to determine whether and how an entity should be scheduled on Google Calendar.
        Actions:
        - DIRECT_EVENT: Fixed timed event/meeting with specific time window
        - FOCUS_BLOCK: Recommended deep-work block for high-priority Q1/Q2 obligation
        - ALL_DAY_MILESTONE: Due date reminder marker on calendar
        - NONE: Standard task kept in knowledge graph
        """
        now = datetime.now()

        # Case 1: Explicitly specified start and end time (appointments, flights, calls)
        if calendar_start:
            return {
                "action": "DIRECT_EVENT",
                "confidence": 0.95,
                "start_time": calendar_start,
                "end_time": calendar_end or calendar_start,
                "summary": node_title,
                "rationale": "Explicit calendar appointment time was provided in note."
            }

        # Case 2: Node is an 'event' or user flagged as calendar candidate with due_date
        if node_type == "event" or is_calendar_candidate:
            if due_date:
                # Construct default 1-hour block on that due date at 10:00 AM
                try:
                    clean_date = due_date.split("T")[0]
                    start_iso = f"{clean_date}T10:00:00"
                    end_iso = f"{clean_date}T11:00:00"
                    return {
                        "action": "DIRECT_EVENT",
                        "confidence": 0.85,
                        "start_time": start_iso,
                        "end_time": end_iso,
                        "summary": node_title,
                        "rationale": "Identified as calendar event with target date."
                    }
                except Exception:
                    pass

        # Case 3: High Priority Q1 Obligation needing focused deep work block
        if quadrant == "Q1_DO_FIRST" and estimated_minutes >= 45:
            # Recommend a Focus Block for today or tomorrow morning
            tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            focus_start = f"{tomorrow}T09:30:00"
            focus_end = f"{tomorrow}T11:00:00"
            return {
                "action": "FOCUS_BLOCK",
                "confidence": 0.75,
                "start_time": focus_start,
                "end_time": focus_end,
                "summary": f"Focus Block: {node_title}",
                "rationale": f"High cognitive load obligation (Q1, est {estimated_minutes}m) qualifies for protected calendar focus block."
            }

        # Case 4: Hard due date present -> All-day milestone
        if due_date and urgency >= 0.7:
            clean_date = due_date.split("T")[0]
            return {
                "action": "ALL_DAY_MILESTONE",
                "confidence": 0.70,
                "start_time": f"{clean_date}T09:00:00",
                "end_time": f"{clean_date}T09:30:00",
                "summary": f"Deadline: {node_title}",
                "rationale": "Urgent deadline scheduled as morning calendar milestone."
            }

        return {
            "action": "NONE",
            "confidence": 0.90,
            "start_time": None,
            "end_time": None,
            "summary": node_title,
            "rationale": "Standard obligation managed within graph task list without calendar clutter."
        }

    def log_decision(
        self,
        entity_id: Optional[str],
        decision_type: str,
        rationale: str,
        input_context: Dict[str, Any],
        output_decision: Dict[str, Any]
    ):
        conn = get_db_connection()
        decision_id = str(uuid.uuid4())
        now = utc_now_iso()
        with conn:
            conn.execute(
                """
                INSERT INTO decision_logs (id, entity_id, decision_type, rationale, input_context_json, output_decision_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    entity_id,
                    decision_type,
                    rationale,
                    json.dumps(input_context, default=str),
                    json.dumps(output_decision, default=str),
                    now
                )
            )
        conn.close()

    def run_proactive_prompt_sweep(self) -> List[Dict[str, Any]]:
        """
        Scans graph for anomalies:
        - Stale projects (no updates for 5+ days)
        - Blocked obligations or waiting_on stalemate (waiting for person > 2 days)
        - Imminent deadlines (< 24 hours)
        Creates entries in prompts_and_nudges table.
        """
        conn = get_db_connection()
        now = datetime.now(timezone.utc)
        created_prompts = []

        # 1. Check for impending deadlines (< 24h)
        impending = conn.execute(
            """
            SELECT * FROM nodes 
            WHERE node_type = 'obligation' 
              AND status IN ('pending', 'in_progress') 
              AND due_date IS NOT NULL
            """
        ).fetchall()

        for row in impending:
            node = dict(row)
            due_str = node["due_date"]
            try:
                clean_due = due_str.replace("Z", "+00:00")
                if "T" in clean_due:
                    dt_due = datetime.fromisoformat(clean_due)
                else:
                    dt_due = datetime.fromisoformat(clean_due + "T23:59:59+00:00")
                if dt_due.tzinfo is None:
                    dt_due = dt_due.replace(tzinfo=timezone.utc)

                diff_hours = (dt_due - now).total_seconds() / 3600.0
                if 0 <= diff_hours <= 24:
                    # Check if prompt already exists
                    existing = conn.execute(
                        "SELECT id FROM prompts_and_nudges WHERE target_node_id = ? AND prompt_type = 'upcoming_deadline' AND status = 'active'",
                        (node["id"],)
                    ).fetchone()
                    if not existing:
                        p_id = str(uuid.uuid4())
                        title = f"Due soon: {node['title'][:30]}"
                        msg = f"'{node['title']}' is due in {round(diff_hours, 1)} hours ({node['due_date']}). Need time to wrap this up?"
                        conn.execute(
                            """
                            INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                            VALUES (?, 'upcoming_deadline', ?, ?, ?, 'active', ?, ?)
                            """,
                            (p_id, title, msg, node["id"], json.dumps({"due_date": due_str, "hours_left": diff_hours}), utc_now_iso())
                        )
                        created_prompts.append({"id": p_id, "title": title, "message": msg})
            except Exception as e:
                logger.debug(f"Error parsing due date for prompt: {e}")

        # 2. Check for waiting_on stalemate
        waiting_nodes = conn.execute(
            """
            SELECT n.id, n.title, n.updated_at, ed.target_id, p.title as person_name
            FROM nodes n
            JOIN edges ed ON n.id = ed.source_id AND ed.relation_type = 'WAITING_ON'
            JOIN nodes p ON ed.target_id = p.id
            WHERE n.status = 'waiting_on'
            """
        ).fetchall()

        for row in waiting_nodes:
            nid = row["id"]
            updated_at = row["updated_at"]
            person_name = row["person_name"]
            try:
                dt_up = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if dt_up.tzinfo is None:
                    dt_up = dt_up.replace(tzinfo=timezone.utc)
                hours_waiting = (now - dt_up).total_seconds() / 3600.0

                if hours_waiting >= 48:
                    existing = conn.execute(
                        "SELECT id FROM prompts_and_nudges WHERE target_node_id = ? AND prompt_type = 'waiting_on_stalemate' AND status = 'active'",
                        (nid,)
                    ).fetchone()
                    if not existing:
                        p_id = str(uuid.uuid4())
                        title = f"Follow up with {person_name}?"
                        msg = f"You've been waiting on {person_name} for '{row['title']}' for {int(hours_waiting // 24)} days. Ready to send a nudge?"
                        conn.execute(
                            """
                            INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                            VALUES (?, 'waiting_on_stalemate', ?, ?, ?, 'active', ?, ?)
                            """,
                            (p_id, title, msg, nid, json.dumps({"person": person_name, "hours_waiting": hours_waiting}), utc_now_iso())
                        )
                        created_prompts.append({"id": p_id, "title": title, "message": msg})
            except Exception as e:
                logger.debug(f"Error checking waiting_on prompt: {e}")

        # 3. Check for Stale Projects
        stale_projects = conn.execute(
            """
            SELECT id, title, updated_at FROM nodes 
            WHERE node_type = 'project' AND status = 'in_progress'
            """
        ).fetchall()

        for p in stale_projects:
            pid = p["id"]
            try:
                dt_p = datetime.fromisoformat(p["updated_at"].replace("Z", "+00:00"))
                if dt_p.tzinfo is None:
                    dt_p = dt_p.replace(tzinfo=timezone.utc)
                days_stale = (now - dt_p).total_seconds() / 86400.0
                if days_stale >= 6:
                    existing = conn.execute(
                        "SELECT id FROM prompts_and_nudges WHERE target_node_id = ? AND prompt_type = 'stale_project' AND status = 'active'",
                        (pid,)
                    ).fetchone()
                    if not existing:
                        p_id = str(uuid.uuid4())
                        title = f"Stale Project: {p['title'][:25]}"
                        msg = f"Project '{p['title']}' has had no activity in {int(days_stale)} days. Would you like to review next actions or defer it?"
                        conn.execute(
                            """
                            INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                            VALUES (?, 'stale_project', ?, ?, ?, 'active', ?, ?)
                            """,
                            (p_id, title, msg, pid, json.dumps({"days_stale": days_stale}), utc_now_iso())
                        )
                        created_prompts.append({"id": p_id, "title": title, "message": msg})
            except Exception as e:
                logger.debug(f"Error checking stale projects: {e}")

        # 4. Check for Stale Social / Family / Key Contacts (> 14 days without interaction)
        stale_people = conn.execute(
            """
            SELECT id, title, updated_at, metadata_json FROM nodes
            WHERE node_type = 'person'
            """
        ).fetchall()

        for pr in stale_people:
            pid = pr["id"]
            name = pr["title"]
            try:
                dt_p = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
                if dt_p.tzinfo is None:
                    dt_p = dt_p.replace(tzinfo=timezone.utc)
                days_since = (now - dt_p).total_seconds() / 86400.0
                if days_since >= 14:
                    existing = conn.execute(
                        "SELECT id FROM prompts_and_nudges WHERE target_node_id = ? AND prompt_type = 'stale_contact' AND status = 'active'",
                        (pid,)
                    ).fetchone()
                    if not existing:
                        p_id = str(uuid.uuid4())
                        title = f"Check in with {name}?"
                        msg = f"It's been {int(days_since)} days since your last note involving {name}. A quick hello keeps personal obligations warm!"
                        conn.execute(
                            """
                            INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                            VALUES (?, 'stale_contact', ?, ?, ?, 'active', ?, ?)
                            """,
                            (p_id, title, msg, pid, json.dumps({"days_since": days_since}), utc_now_iso())
                        )
                        created_prompts.append({"id": p_id, "title": title, "message": msg})
            except Exception as e:
                logger.debug(f"Error checking stale contacts: {e}")

        # 5. Check for Pending Elicitations needing clarification (> 4h old)
        pending_els = conn.execute(
            """
            SELECT e.id, e.question, e.node_id, n.title as task_title, e.created_at
            FROM elicitations e
            JOIN nodes n ON e.node_id = n.id
            WHERE e.status = 'pending'
            """
        ).fetchall()

        for el in pending_els:
            el_id = el["id"]
            task_title = el["task_title"]
            try:
                dt_el = datetime.fromisoformat(el["created_at"].replace("Z", "+00:00"))
                if dt_el.tzinfo is None:
                    dt_el = dt_el.replace(tzinfo=timezone.utc)
                hours_el = (now - dt_el).total_seconds() / 3600.0
                if hours_el >= 4:
                    existing = conn.execute(
                        "SELECT id FROM prompts_and_nudges WHERE target_node_id = ? AND prompt_type = 'pending_elicitation' AND status = 'active'",
                        (el["node_id"],)
                    ).fetchone()
                    if not existing:
                        p_id = str(uuid.uuid4())
                        title = f"Clarification: {task_title[:25]}"
                        msg = f"'{task_title}' needs a detail: {el['question']}"
                        conn.execute(
                            """
                            INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                            VALUES (?, 'pending_elicitation', ?, ?, ?, 'active', ?, ?)
                            """,
                            (p_id, title, msg, el["node_id"], json.dumps({"elicitation_id": el_id}), utc_now_iso())
                        )
                        created_prompts.append({"id": p_id, "title": title, "message": msg})
            except Exception as e:
                logger.debug(f"Error checking pending elicitations: {e}")

        conn.commit()
        conn.close()
        return created_prompts

    def get_active_prompts(self) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM prompts_and_nudges WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["action_data"] = json.loads(d.get("action_data_json") or "{}")
            result.append(d)
        return result

    def resolve_prompt(self, prompt_id: str, new_status: str = "resolved") -> bool:
        conn = get_db_connection()
        with conn:
            conn.execute(
                "UPDATE prompts_and_nudges SET status = ?, resolved_at = ? WHERE id = ?",
                (new_status, utc_now_iso(), prompt_id)
            )
        conn.close()
        return True

    def review_workload_capacity(
        self,
        new_obligation: Optional[Dict[str, Any]] = None,
        notify_phone: bool = True
    ) -> Dict[str, Any]:
        """
        Reviews total current workload, Eisenhower stress distribution, and deadline collisions.
        Flags a risk if the user is overcommitted, taking on too much, or facing severe bottlenecks.
        """
        from app.services.crypto_service import crypto_service

        conn = get_db_connection()
        now = datetime.now(timezone.utc)
        today_date_str = now.strftime("%Y-%m-%d")

        # 1. Fetch all active obligations
        rows = conn.execute("""
            SELECT id, title, node_type, category, status, priority,
                   urgency_score, importance_score, eisenhower_quadrant,
                   due_date, scheduled_start, energy_required, estimated_minutes, description
            FROM nodes
            WHERE node_type = 'obligation'
              AND status IN ('pending', 'in_progress', 'waiting_on', 'blocked')
        """).fetchall()

        active_obligations = []
        for r in rows:
            d = dict(r)
            d["title"] = crypto_service.decrypt(d.get("title")) or "Untitled Obligation"
            d["description"] = crypto_service.decrypt(d.get("description")) or ""
            active_obligations.append(d)

        total_active = len(active_obligations)
        q1_tasks = [o for o in active_obligations if o.get("eisenhower_quadrant") == "Q1_DO_FIRST"]
        q2_tasks = [o for o in active_obligations if o.get("eisenhower_quadrant") == "Q2_SCHEDULE"]
        q1_count = len(q1_tasks)
        q2_count = len(q2_tasks)
        high_energy_count = len([o for o in active_obligations if o.get("energy_required") == "high"])

        # Total estimated focus hours
        total_estimated_minutes = sum(o.get("estimated_minutes") or 30 for o in active_obligations)
        total_estimated_hours = round(total_estimated_minutes / 60.0, 1)

        # Overdue tasks
        overdue_tasks = []
        for o in active_obligations:
            due = o.get("due_date")
            if due:
                clean_due = due.split("T")[0]
                if clean_due < today_date_str:
                    overdue_tasks.append(o)
        overdue_count = len(overdue_tasks)

        # Collisions with new obligation (or same-day clusters)
        target_due_date = None
        same_day_conflicts = []
        same_day_minutes = 0

        new_title = "New Obligation"
        new_id = None
        if new_obligation:
            new_title = new_obligation.get("title") or "New Obligation"
            new_id = new_obligation.get("id")
            raw_due = new_obligation.get("due_date")
            if raw_due:
                target_due_date = raw_due.split("T")[0]
                same_day_conflicts = [
                    o for o in active_obligations
                    if o.get("due_date") and o["due_date"].split("T")[0] == target_due_date and o.get("id") != new_id
                ]
                same_day_minutes = (new_obligation.get("estimated_minutes") or 30) + sum(
                    o.get("estimated_minutes") or 30 for o in same_day_conflicts
                )

        # If no specific new_obligation due date, look for the most clustered upcoming date
        if not target_due_date:
            date_counts = {}
            for o in active_obligations:
                due = o.get("due_date")
                if due:
                    d_str = due.split("T")[0]
                    if d_str >= today_date_str:
                        date_counts[d_str] = date_counts.get(d_str, 0) + 1
            if date_counts:
                max_date = max(date_counts, key=date_counts.get)
                if date_counts[max_date] >= 2:
                    target_due_date = max_date
                    same_day_conflicts = [o for o in active_obligations if o.get("due_date") and o["due_date"].split("T")[0] == target_due_date]
                    same_day_minutes = sum(o.get("estimated_minutes") or 30 for o in same_day_conflicts)

        # 2. Risk Evaluation Algorithm
        # Compute stress score (0 to 100)
        stress_score = 0
        stress_score += min(40, q1_count * 8) # Q1 tasks contribute heavily to stress
        stress_score += min(20, total_active * 1.2) # General volume
        stress_score += min(20, len(same_day_conflicts) * 7) # Same day clustering
        stress_score += min(20, overdue_count * 6) # Unresolved past due
        stress_score = min(100, int(stress_score))

        # Risk level determination
        if q1_count >= 6 or len(same_day_conflicts) >= 4 or same_day_minutes >= 360 or (overdue_count >= 3 and total_active >= 18):
            risk_level = "critical"
        elif q1_count >= 4 or len(same_day_conflicts) >= 3 or same_day_minutes >= 240 or total_active >= 20:
            risk_level = "high"
        elif q1_count >= 3 or len(same_day_conflicts) >= 2 or same_day_minutes >= 150 or total_active >= 12:
            risk_level = "medium"
        else:
            risk_level = "low"

        risk_flagged = risk_level in ("medium", "high", "critical")

        # 3. Recommendations & Summary Generation
        conflict_summaries = [
            {"id": c["id"], "title": c["title"], "due_date": c.get("due_date"), "priority": c.get("priority"), "quadrant": c.get("eisenhower_quadrant")}
            for c in same_day_conflicts[:4]
        ]

        if not risk_flagged:
            summary = "Workload capacity is healthy. Your current schedule has ample buffer."
            details = f"You have {total_active} active obligations ({q1_count} urgent Q1) totaling ~{total_estimated_hours}h estimated focus time."
            recommendations = ["Maintain focus on Q2 scheduled priorities to prevent future crunch."]
        else:
            recommendations = []
            # Deterministic base recommendations
            if target_due_date and same_day_conflicts:
                conflict_titles = ", ".join([f"'{c['title']}'" for c in same_day_conflicts[:2]])
                summary = f"Workload Alert ({risk_level.upper()}): {len(same_day_conflicts) + 1} obligations due on {target_due_date} totaling ~{round(same_day_minutes / 60, 1)}h focus time."
                details = f"Adding '{new_title}' collides with {conflict_titles} on {target_due_date}. You currently have {q1_count} urgent Q1 tasks active."
                recommendations.append(f"Consider rescheduling '{new_title}' or {same_day_conflicts[0]['title']} to later in the week.")
            else:
                summary = f"Workload Alert ({risk_level.upper()}): High cognitive load with {q1_count} urgent Q1 obligations active ({total_active} total in flight)."
                details = f"Taking on '{new_title}' increases total active backlog to {total_active} obligations (~{total_estimated_hours}h estimated)."
                recommendations.append("Prioritize the top 2 urgent Q1 tasks and defer lower-priority Q3/Q4 obligations.")

            if q1_count >= 4:
                recommendations.append(f"You have {q1_count} urgent 'Do First' tasks. Delegate or negotiate deadlines to avoid burnout.")
            if overdue_count > 0:
                recommendations.append(f"Resolve or reschedule {overdue_count} overdue task(s) before committing to new work.")

            # Attempt brief AI enhancement via Gemini for natural phrasing
            try:
                from app.services.gemini_service import gemini_service
                est_m = new_obligation.get('estimated_minutes', 30) if new_obligation else 30
                ai_prompt = f"""
A personal assistant user added: '{new_title}' (Due: {target_due_date or 'No date'}, Est: {est_m}m).
Current active load: {total_active} obligations, {q1_count} urgent Q1 tasks, {len(same_day_conflicts)} collision(s) on same day.
Risk: {risk_level.upper()} ({stress_score}% capacity load).

Provide JSON with:
1. summary: A direct, 1-sentence warning
2. recommendations: Array of 2 actionable bullet advice
Format: {{"summary": "...", "recommendations": ["...", "..."]}}
"""
                ai_resp = gemini_service.generate_text(ai_prompt, temperature=0.2)
                if ai_resp:
                    clean_json = ai_resp.strip()
                    if "```json" in clean_json:
                        clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_json:
                        clean_json = clean_json.split("```")[1].split("```")[0].strip()
                    parsed = json.loads(clean_json)
                    if parsed.get("summary"):
                        summary = parsed["summary"]
                    if parsed.get("recommendations") and isinstance(parsed["recommendations"], list):
                        recommendations = parsed["recommendations"]
            except Exception as e:
                logger.debug(f"Gemini workload enhancement skipped: {e}")

        assessment_result = {
            "risk_level": risk_level,
            "risk_flagged": risk_flagged,
            "stress_score": stress_score,
            "total_active_obligations": total_active,
            "q1_urgent_count": q1_count,
            "colliding_deadlines_count": len(same_day_conflicts),
            "overdue_count": overdue_count,
            "estimated_focus_hours": round(total_estimated_hours, 1),
            "summary": summary,
            "details": details,
            "metrics": {
                "active_obligations_count": total_active,
                "q1_do_first_count": q1_count,
                "q2_schedule_count": q2_count,
                "high_energy_count": high_energy_count,
                "overdue_count": overdue_count,
                "same_day_conflicts_count": len(same_day_conflicts),
                "target_date_focus_minutes": same_day_minutes,
                "total_estimated_focus_hours": total_estimated_hours
            },
            "recommendations": recommendations[:3],
            "conflicting_obligations": conflict_summaries
        }

        # 4. If risk flagged, persist prompt and log decision
        if risk_flagged and new_obligation:
            # Check for existing prompt for this target
            existing_p = conn.execute(
                "SELECT id FROM prompts_and_nudges WHERE target_node_id = ? AND prompt_type = 'workload_overload_risk' AND status = 'active'",
                (new_id,)
            ).fetchone() if new_id else None

            if not existing_p:
                p_id = str(uuid.uuid4())
                prompt_title = f"⚠️ Overload Risk: {new_title[:25]}"
                conn.execute("""
                    INSERT INTO prompts_and_nudges (
                        id, prompt_type, title, message, target_node_id, status, action_data_json, created_at
                    ) VALUES (?, 'workload_overload_risk', ?, ?, ?, 'active', ?, ?)
                """, (
                    p_id, prompt_title, summary, new_id,
                    json.dumps(assessment_result, default=str), utc_now_iso()
                ))
            conn.commit()

        conn.close()

        if risk_flagged and new_obligation:
            # Log decision
            self.log_decision(
                entity_id=new_id,
                decision_type="WORKLOAD_CAPACITY_REVIEW",
                rationale=summary,
                input_context={"new_obligation": new_obligation, "total_active": total_active, "q1_count": q1_count},
                output_decision=assessment_result
            )

        # 5. Push notification to Pixel 10 XL if high or critical
        if notify_phone and risk_level in ("high", "critical") and new_obligation:
            try:
                from app.services.notification_service import notification_service
                notification_service.send_notification(
                    title="Obrigado · Workload Overload Alert ⚠️",
                    body=f"Adding '{new_title[:35]}' causes a schedule bottleneck ({q1_count} urgent tasks active). Tap to review capacity.",
                    url="/?tab=matrix",
                    category="urgent_nudge",
                    priority="urgent",
                    tags="warning,alarm_clock"
                )
            except Exception as e:
                logger.debug(f"Phone push for workload risk skipped: {e}")

        return assessment_result

decision_engine = DecisionEngine()
