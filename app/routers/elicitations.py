import json
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException

from app.database import get_db_connection, utc_now_iso
from app.models.schemas import ElicitationAnswerRequest, NodeUpdate
from app.services.graph_service import graph_service
from app.services.gemini_service import gemini_service
from app.services.decision_engine import decision_engine
from app.services.crypto_service import crypto_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/elicitations", tags=["elicitations"])

@router.get("/pending")
async def get_pending_elicitations():
    """Retrieve all pending elicitation questions requiring user input to complete records."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT e.*, n.title as node_title, n.node_type, n.category
        FROM elicitations e
        JOIN nodes n ON e.node_id = n.id
        WHERE e.status = 'pending'
        ORDER BY e.created_at DESC
        """
    ).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        d["question"] = crypto_service.decrypt(d.get("question")) or ""
        d["node_title"] = crypto_service.decrypt(d.get("node_title")) or ""
        d["user_response"] = crypto_service.decrypt(d.get("user_response")) if d.get("user_response") else None
        d["suggested_options"] = json.loads(d.get("suggested_options_json") or "[]")
        results.append(d)
    return results

@router.post("/answer")
async def answer_elicitation(req: ElicitationAnswerRequest):
    """
    Submit user answer to an elicitation question.
    Gemini refines the record, updates the graph, links people/projects, and marks elicitation resolved.
    """
    conn = get_db_connection()
    elicitation = conn.execute("SELECT * FROM elicitations WHERE id = ?", (req.elicitation_id,)).fetchone()
    if not elicitation:
        conn.close()
        raise HTTPException(status_code=404, detail="Elicitation not found.")

    node_id = elicitation["node_id"]
    node = graph_service.get_node_by_id(node_id)
    if not node:
        conn.close()
        raise HTTPException(status_code=404, detail="Target node not found.")

    now = utc_now_iso()
    decrypted_question = crypto_service.decrypt(elicitation["question"]) or ""

    # 1. Ask Gemini to refine record using the elicited answer
    refined = gemini_service.refine_node_with_elicitation(
        node=node,
        question=decrypted_question,
        user_answer=req.user_answer
    )

    # 2. Update Node
    update_data = NodeUpdate()
    if refined.get("title"): update_data.title = refined["title"]
    if refined.get("description"): update_data.description = refined["description"]
    if refined.get("due_date"): update_data.due_date = refined["due_date"]
    if refined.get("category"): update_data.category = refined["category"]
    if refined.get("priority"): update_data.priority = refined["priority"]
    if refined.get("urgency_score") is not None: update_data.urgency_score = float(refined["urgency_score"])
    if refined.get("importance_score") is not None: update_data.importance_score = float(refined["importance_score"])

    updated_node = graph_service.update_node(node_id, update_data)

    # 3. If person identity facts were elicited, save them
    if refined.get("memory_facts_to_save"):
        with conn:
            for fact in refined["memory_facts_to_save"]:
                import uuid
                conn.execute(
                    """
                    INSERT INTO person_memories (id, person_node_id, memory_fact, category, source_note_id, created_at)
                    VALUES (?, ?, ?, 'elicited', ?, ?)
                    """,
                    (str(uuid.uuid4()), node_id, crypto_service.encrypt(fact), elicitation["source_note_id"], now)
                )

    # 4. Mark elicitation as answered (encrypted)
    with conn:
        conn.execute(
            """
            UPDATE elicitations 
            SET status = 'answered', user_response = ?, answered_at = ?
            WHERE id = ?
            """,
            (crypto_service.encrypt(req.user_answer), now, req.elicitation_id)
        )
    conn.close()

    # 5. Log Decision
    decision_engine.log_decision(
        entity_id=node_id,
        decision_type="ELICITATION_RECORD_REFINEMENT",
        rationale=f"Record '{node['title']}' refined via user elicitation answer: '{req.user_answer}'",
        input_context={"question": elicitation["question"], "answer": req.user_answer},
        output_decision=refined
    )

    return {
        "success": True,
        "updated_node": updated_node,
        "refined_fields": refined
    }

@router.post("/{elicitation_id}/dismiss")
async def dismiss_elicitation(elicitation_id: str):
    conn = get_db_connection()
    with conn:
        conn.execute(
            "UPDATE elicitations SET status = 'dismissed', answered_at = ? WHERE id = ?",
            (utc_now_iso(), elicitation_id)
        )
    conn.close()
    return {"success": True}
