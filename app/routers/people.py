import uuid
import json
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException

from app.database import get_db_connection, utc_now_iso
from app.models.schemas import AddPersonMemoryRequest, UpdatePersonProfileRequest, NodeUpdate
from app.services.graph_service import graph_service
from app.services.crypto_service import crypto_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/people", tags=["people"])

@router.get("")
async def list_people():
    """
    List all people in the knowledge graph with their role, organization, relationship sphere,
    memory facts, open commitments (owed to/from them), and recent interaction dates.
    """
    conn = get_db_connection()
    people_nodes = conn.execute(
        "SELECT * FROM nodes WHERE node_type = 'person' ORDER BY updated_at DESC"
    ).fetchall()

    results = []
    for row in people_nodes:
        p = dict(row)
        pid = p["id"]
        p["title"] = crypto_service.decrypt(p.get("title")) or ""
        p["description"] = crypto_service.decrypt(p.get("description")) or ""
        meta_raw = crypto_service.decrypt(p.get("metadata_json")) or "{}"
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}

        # 1. Fetch memories
        mems = conn.execute(
            "SELECT id, memory_fact, category, created_at FROM person_memories WHERE person_node_id = ? ORDER BY created_at DESC",
            (pid,)
        ).fetchall()
        decrypted_mems = []
        for m in mems:
            md = dict(m)
            md["memory_fact"] = crypto_service.decrypt(md.get("memory_fact")) or ""
            decrypted_mems.append(md)

        # 2. Obligations I owe them or that involve them
        involving = conn.execute(
            """
            SELECT n.id, n.title, n.status, n.due_date, n.priority, ed.relation_type
            FROM edges ed
            JOIN nodes n ON ed.source_id = n.id
            WHERE ed.target_id = ? AND n.status != 'completed'
            """,
            (pid,)
        ).fetchall()

        commitments_from_them = []
        commitments_to_them = []
        for r in involving:
            rd = dict(r)
            rd["title"] = crypto_service.decrypt(rd.get("title")) or ""
            if rd["relation_type"] == "WAITING_ON":
                commitments_from_them.append(rd)
            else:
                commitments_to_them.append(rd)

        # 3. Projects connected
        projects = conn.execute(
            """
            SELECT DISTINCT proj.id, proj.title
            FROM edges ed1
            JOIN edges ed2 ON ed1.source_id = ed2.source_id
            JOIN nodes proj ON ed2.target_id = proj.id AND proj.node_type = 'project'
            WHERE ed1.target_id = ?
            """,
            (pid,)
        ).fetchall()
        decrypted_projects = []
        for pr in projects:
            prd = dict(pr)
            prd["title"] = crypto_service.decrypt(prd.get("title")) or ""
            decrypted_projects.append(prd)

        results.append({
            "id": pid,
            "name": p["title"],
            "role_or_title": meta.get("role_or_title") or p["description"] or "Contact",
            "organization": meta.get("organization") or "",
            "relationship_type": meta.get("relationship_type") or "colleague",
            "category": p["category"],
            "memories": decrypted_mems,
            "commitments_from_them": commitments_from_them, # what we are waiting on them for
            "commitments_to_them": commitments_to_them,     # tasks involving them
            "projects": decrypted_projects,
            "updated_at": p["updated_at"]
        })

    conn.close()
    return results

@router.get("/{person_id}")
async def get_person_dossier(person_id: str):
    """Retrieve full Person Dossier with all memory facts, timeline, and obligations."""
    node = graph_service.get_node_by_id(person_id)
    if not node or node["node_type"] != "person":
        raise HTTPException(status_code=404, detail="Person not found.")

    conn = get_db_connection()
    meta = json.loads(node.get("metadata_json") or "{}")

    # Memories
    memories = conn.execute(
        "SELECT id, memory_fact, category, created_at FROM person_memories WHERE person_node_id = ? ORDER BY created_at DESC",
        (person_id,)
    ).fetchall()
    decrypted_memories = []
    for m in memories:
        md = dict(m)
        md["memory_fact"] = crypto_service.decrypt(md.get("memory_fact")) or ""
        decrypted_memories.append(md)

    # All related obligations (both active and completed)
    obligations = conn.execute(
        """
        SELECT n.id, n.title, n.status, n.due_date, n.priority, n.category, ed.relation_type, n.completed_at
        FROM edges ed
        JOIN nodes n ON ed.source_id = n.id
        WHERE ed.target_id = ?
        ORDER BY n.updated_at DESC
        """,
        (person_id,)
    ).fetchall()
    decrypted_obligations = []
    for o in obligations:
        od = dict(o)
        od["title"] = crypto_service.decrypt(od.get("title")) or ""
        decrypted_obligations.append(od)

    conn.close()

    return {
        "person": node,
        "profile": {
            "role_or_title": meta.get("role_or_title") or node["description"],
            "organization": meta.get("organization") or "",
            "relationship_type": meta.get("relationship_type") or "colleague"
        },
        "memories": decrypted_memories,
        "obligations": decrypted_obligations
    }

@router.post("/{person_id}/memories")
async def add_person_memory(person_id: str, req: AddPersonMemoryRequest):
    """Add a personal fact, preference, or context memory to remember about this person."""
    node = graph_service.get_node_by_id(person_id)
    if not node:
        raise HTTPException(status_code=404, detail="Person not found.")

    memory_id = str(uuid.uuid4())
    now = utc_now_iso()
    enc_fact = crypto_service.encrypt(req.memory_fact)

    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO person_memories (id, person_node_id, memory_fact, category, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_id, person_id, enc_fact, req.category, now)
        )
    conn.close()

    return {
        "id": memory_id,
        "person_id": person_id,
        "memory_fact": req.memory_fact,
        "category": req.category,
        "created_at": now
    }

@router.delete("/memories/{memory_id}")
async def delete_person_memory(memory_id: str):
    conn = get_db_connection()
    with conn:
        conn.execute("DELETE FROM person_memories WHERE id = ?", (memory_id,))
    conn.close()
    return {"success": True}

@router.patch("/{person_id}")
async def update_person_profile(person_id: str, req: UpdatePersonProfileRequest):
    node = graph_service.get_node_by_id(person_id)
    if not node:
        raise HTTPException(status_code=404, detail="Person not found.")

    meta = json.loads(node.get("metadata_json") or "{}")
    if req.role_or_title is not None: meta["role_or_title"] = req.role_or_title
    if req.organization is not None: meta["organization"] = req.organization
    if req.relationship_type is not None: meta["relationship_type"] = req.relationship_type

    desc = f"{meta.get('role_or_title', '')} at {meta.get('organization', '')}".strip(" at ")
    updated = graph_service.update_node(person_id, NodeUpdate(
        description=desc,
        metadata=meta
    ))
    return updated
