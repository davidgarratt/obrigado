from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone, timedelta

from app.services.graph_service import graph_service
from app.models.schemas import NodeUpdate
from app.database import get_db_connection

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
