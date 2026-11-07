from typing import Optional, List, Dict, Any
import json
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone, timedelta

from app.services.graph_service import graph_service
from app.services.gemini_service import gemini_service
from app.services.decision_engine import decision_engine
from app.models.schemas import (
    NodeUpdate,
    NodeCreate,
    EdgeCreate,
    ObligationUpdateRequest,
    ObligationUpdateResponse
)
from app.database import get_db_connection, utc_now_iso

router = APIRouter(prefix="/api/obligations", tags=["obligations"])

@router.get("/eisenhower")
async def get_eisenhower_matrix(category: Optional[str] = None):
    """
    Returns obligations organized into the 4 Eisenhower Quadrants:
    - Q1: Do First (Urgent & Important)
    - Q2: Schedule / Strategic (Not Urgent & Important)
    - Q3: Delegate / Quick Nudge (Urgent & Not Important)
    - Q4: Backlog / Someday (Not Urgent & Not Important)
    """
    all_obligations = graph_service.get_all_nodes(node_type="obligation", category=category)
    active = [o for o in all_obligations if o["status"] in ("pending", "in_progress", "waiting_on", "blocked")]

    q1 = [o for o in active if o["eisenhower_quadrant"] == "Q1_DO_FIRST"]
    q2 = [o for o in active if o["eisenhower_quadrant"] == "Q2_SCHEDULE"]
    q3 = [o for o in active if o["eisenhower_quadrant"] == "Q3_DELEGATE"]
    q4 = [o for o in active if o["eisenhower_quadrant"] == "Q4_DONT_DO"]

    # Sort each quadrant by combined utility
    q1.sort(key=lambda x: (x["urgency_score"] + x["importance_score"]), reverse=True)
    q2.sort(key=lambda x: (x["importance_score"], x["urgency_score"]), reverse=True)
    q3.sort(key=lambda x: (x["urgency_score"]), reverse=True)
    q4.sort(key=lambda x: (x["created_at"]), reverse=True)

    return {
        "Q1_DO_FIRST": q1,
        "Q2_SCHEDULE": q2,
        "Q3_DELEGATE": q3,
        "Q4_DONT_DO": q4,
        "counts": {
            "Q1": len(q1),
            "Q2": len(q2),
            "Q3": len(q3),
            "Q4": len(q4),
            "total_active": len(active)
        }
    }

@router.get("/workload-capacity")
async def get_workload_capacity():
    """
    Returns real-time cognitive workload capacity, stress score, and overload risk assessment.
    """
    from app.services.decision_engine import decision_engine
    return decision_engine.review_workload_capacity(new_obligation=None, notify_phone=False)

@router.get("/projects")
async def get_projects_overview(category: Optional[str] = None):
    """Retrieve all projects along with their linked obligations, progress, and blockers."""
    projects = graph_service.get_all_nodes(node_type="project", category=category)
    all_obligations = graph_service.get_all_nodes(node_type="obligation")
    edges = graph_service.get_all_edges()

    results = []
    for p in projects:
        p_id = p["id"]
        # Find obligations connected to this project via PART_OF
        part_of_ids = [e["source_id"] for e in edges if e["target_id"] == p_id and e["relation_type"] == "PART_OF"]
        linked = [o for o in all_obligations if o["id"] in part_of_ids]

        completed = [o for o in linked if o["status"] == "completed"]
        in_progress = [o for o in linked if o["status"] == "in_progress"]
        blocked = [o for o in linked if o["status"] == "blocked"]
        pending = [o for o in linked if o["status"] == "pending"]

        total = len(linked)
        pct = int(len(completed) / total * 100) if total > 0 else 0

        results.append({
            "project": p,
            "obligations": linked,
            "metrics": {
                "total": total,
                "completed": len(completed),
                "in_progress": len(in_progress),
                "blocked": len(blocked),
                "pending": len(pending),
                "progress_percent": pct
            }
        })

    return results

@router.get("/waiting-on")
async def get_waiting_on_items():
    """Retrieve all obligations currently blocked waiting on people or entities."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT n.*, p.title as person_name, p.id as person_id, ed.metadata_json as relation_meta
        FROM nodes n
        JOIN edges ed ON n.id = ed.source_id AND ed.relation_type = 'WAITING_ON'
        JOIN nodes p ON ed.target_id = p.id
        WHERE n.status = 'waiting_on'
        ORDER BY n.updated_at ASC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.post("/{node_id}/toggle-status")
async def toggle_obligation_status(node_id: str):
    """Quick toggle between pending and completed."""
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Obligation not found.")

    new_status = "completed" if node["status"] != "completed" else "pending"
    updated = graph_service.update_node(node_id, NodeUpdate(status=new_status))

    unblocked = []
    if new_status == "completed":
        unblocked = graph_service.check_unblocked_dependents(node_id)

    return {
        "node": updated,
        "new_status": new_status,
        "unblocked_dependents": unblocked
    }

@router.post("/{node_id}/snooze")
async def snooze_obligation(node_id: str, days: int = 1):
    """Push due date forward by N days."""
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Obligation not found.")

    new_due = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    updated = graph_service.update_node(node_id, NodeUpdate(due_date=new_due, status="pending"))
    return {"node": updated, "new_due_date": new_due}

@router.get("/{node_id}/details")
async def get_obligation_details(node_id: str):
    """Retrieve full details of an obligation including connected project, blockers, people, and progress history."""
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Obligation not found.")

    edges = graph_service.get_all_edges()
    all_nodes = graph_service.get_all_nodes()
    node_map = {n["id"]: n for n in all_nodes}

    # Find connected project (PART_OF)
    linked_project = None
    for e in edges:
        if e["source_id"] == node_id and e["relation_type"] == "PART_OF":
            linked_project = node_map.get(e["target_id"])
            if linked_project:
                break

    # Find people waiting on (WAITING_ON)
    waiting_on_people = []
    for e in edges:
        if e["source_id"] == node_id and e["relation_type"] == "WAITING_ON":
            person = node_map.get(e["target_id"])
            if person:
                waiting_on_people.append(person)

    # Dependencies (tasks this node DEPENDS_ON)
    dependencies = []
    for e in edges:
        if e["source_id"] == node_id and e["relation_type"] == "DEPENDS_ON":
            dep = node_map.get(e["target_id"])
            if dep:
                dependencies.append(dep)

    # Dependents (tasks that DEPEND on this node)
    dependents = []
    for e in edges:
        if e["target_id"] == node_id and e["relation_type"] == "DEPENDS_ON":
            dep = node_map.get(e["source_id"])
            if dep:
                dependents.append(dep)

    # Progress updates history from metadata
    meta = {}
    try:
        meta = json.loads(node.get("metadata_json") or "{}")
    except Exception:
        meta = {}
    progress_updates = meta.get("progress_updates", [])

    return {
        "node": node,
        "project": linked_project,
        "waiting_on": waiting_on_people,
        "dependencies": dependencies,
        "dependents": dependents,
        "progress_updates": progress_updates
    }

@router.post("/{node_id}/process-update")
async def process_obligation_update_endpoint(node_id: str, payload: ObligationUpdateRequest):
    """
    Intelligently processes an update for an obligation using Gemini/decision engine:
    - Revises status (completed, waiting_on, in_progress, blocked)
    - Updates due date if revised
    - Updates urgency/importance/quadrant
    - Links persons waited on in graph
    - Checks unblocked dependents if completed
    - Evaluates workload capacity impact
    - Stores progress history and logs decision
    """
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Obligation not found.")

    update_text = payload.update_text.strip()
    if not update_text:
        raise HTTPException(status_code=400, detail="Update text cannot be empty.")

    # 1. Process with AI
    comprehension = gemini_service.process_obligation_update(node, update_text)

    # 2. Extract updates
    node_update_kwargs = {}

    new_status = comprehension.get("status")
    if new_status and new_status in ("pending", "in_progress", "waiting_on", "blocked", "completed"):
        node_update_kwargs["status"] = new_status

    new_due = comprehension.get("due_date")
    if new_due:
        node_update_kwargs["due_date"] = new_due

    urgency = comprehension.get("urgency_score")
    if urgency is not None:
        try:
            node_update_kwargs["urgency_score"] = float(urgency)
        except (ValueError, TypeError):
            pass

    importance = comprehension.get("importance_score")
    if importance is not None:
        try:
            node_update_kwargs["importance_score"] = float(importance)
        except (ValueError, TypeError):
            pass

    # Progress notes and audit log
    prog_note = comprehension.get("progress_note") or update_text
    meta = {}
    try:
        meta = json.loads(node.get("metadata_json") or "{}")
    except Exception:
        meta = {}
    updates_list = meta.get("progress_updates", [])
    now_str = utc_now_iso()
    updates_list.append({
        "timestamp": now_str,
        "update_text": update_text,
        "changes_summary": comprehension.get("changes_summary", ""),
        "progress_note": prog_note,
        "status": new_status or node.get("status")
    })
    meta["progress_updates"] = updates_list
    node_update_kwargs["metadata"] = meta

    # Append to description if there's a note
    cur_desc = node.get("description") or ""
    date_tag = now_str.split("T")[0]
    updated_desc = f"{cur_desc}\n[{date_tag} Update]: {prog_note}".strip()
    node_update_kwargs["description"] = updated_desc

    # 3. Apply update to node
    updated_node = graph_service.update_node(node_id, NodeUpdate(**node_update_kwargs))

    # 4. Handle waiting on person linking
    waiting_person_name = comprehension.get("waiting_on_person")
    if waiting_person_name:
        waiting_person_name = waiting_person_name.strip()
        person = graph_service.find_node_by_title_or_similarity(waiting_person_name, node_type="person")
        if not person:
            person = graph_service.create_node(NodeCreate(
                title=waiting_person_name,
                node_type="person",
                category="work",
                description=f"Person involved in task: {node.get('title')}"
            ))
        if person:
            graph_service.create_edge(EdgeCreate(
                source_id=node_id,
                target_id=person["id"],
                relation_type="WAITING_ON",
                weight=1.0,
                metadata={"reason": prog_note}
            ))

    # 5. Check unblocked dependents if completed
    unblocked = []
    if (new_status or node.get("status")) == "completed":
        unblocked = graph_service.check_unblocked_dependents(node_id)

    # 6. Re-evaluate workload capacity
    workload_risk = decision_engine.review_workload_capacity(new_obligation=None, notify_phone=False)

    # 7. Log decision
    decision_engine.log_decision(
        entity_id=node_id,
        decision_type="OBLIGATION_UPDATE",
        rationale=comprehension.get("changes_summary", f"Updated obligation: {prog_note}"),
        input_context={
            "update_text": update_text,
            "previous_status": node.get("status"),
            "previous_due_date": node.get("due_date")
        },
        output_decision=comprehension
    )

    return {
        "success": True,
        "node": updated_node,
        "changes_summary": comprehension.get("changes_summary", "Update processed successfully."),
        "comprehension": comprehension,
        "unblocked_dependents": unblocked,
        "workload_risk": workload_risk
    }
