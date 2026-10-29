import os
import uuid
import json
import logging
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks

from app.models.schemas import NoteCaptureRequest, NoteCaptureResponse, NodeCreate, EdgeCreate
from app.services.gemini_service import gemini_service
from app.services.graph_service import graph_service
from app.services.decision_engine import decision_engine
from app.services.calendar_service import calendar_service
from app.services.crypto_service import crypto_service
from app.database import get_db_connection, utc_now_iso
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notes", tags=["notes"])

@router.post("/capture", response_model=NoteCaptureResponse)
async def capture_note(req: NoteCaptureRequest, background_tasks: BackgroundTasks):
    """
    Ingest a quick note, extract entities & relationships, evaluate decisions,
    update knowledge graph, schedule calendar events, and return result.
    """
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Note content cannot be empty.")

    note_id = str(uuid.uuid4())
    now = utc_now_iso()

    # 1. Save raw note (encrypted at rest)
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO raw_notes (id, content, source_type, processed, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (note_id, crypto_service.encrypt(req.content), req.source_type, now)
        )
    conn.close()

    # 2. Retrieve existing nodes to feed context into Gemini for entity resolution
    existing_nodes = graph_service.get_all_nodes()

    # 3. Process with Gemini
    extraction = gemini_service.extract_from_note(
        note_content=req.content,
        existing_nodes_context=existing_nodes
    )

    created_nodes_map = {} # title -> node_dict
    created_entities = []
    created_edges = []
    calendar_actions = []
    prompts_generated = []

    # 4. Process Status Updates (if user note says "I finished the slides for Dave")
    for su in extraction.status_updates:
        matched = graph_service.find_node_by_title_or_similarity(su.target_title)
        if matched:
            from app.models.schemas import NodeUpdate
            graph_service.update_node(matched["id"], NodeUpdate(status=su.new_status))
            # If completed, check for unblocked cascade
            if su.new_status == "completed":
                unblocked = graph_service.check_unblocked_dependents(matched["id"])
                for unb in unblocked:
                    p_id = str(uuid.uuid4())
                    title = f"Unblocked: {unb['title'][:30]}"
                    msg = f"Prerequisite task '{matched['title']}' is now done! '{unb['title']}' is ready for action."
                    conn = get_db_connection()
                    with conn:
                        conn.execute(
                            """
                            INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                            VALUES (?, 'unblocked_cascade', ?, ?, ?, 'active', ?, ?)
                            """,
                            (p_id, title, msg, unb["id"], json.dumps({"unblocked_by": matched["title"]}), utc_now_iso())
                        )
                    conn.close()
                    prompts_generated.append({"id": p_id, "title": title, "message": msg})

    # 5. Create or Resolve Entities
    for ent in extraction.entities:
        # Check if already exists in graph
        existing_entity = graph_service.find_node_by_title_or_similarity(ent.title, ent.node_type)

        if existing_entity:
            # Update existing entity if needed
            created_nodes_map[ent.title] = existing_entity
            created_nodes_map[ent.title.lower().strip()] = existing_entity
            created_entities.append(existing_entity)
            node_id_ref = existing_entity["id"]
        else:
            # Decision Model: Refine Urgency & Importance
            priority_eval = decision_engine.evaluate_obligation_priority(
                base_urgency=ent.urgency_score,
                base_importance=ent.importance_score,
                due_date=ent.due_date,
                category=ent.category,
                energy_required=ent.energy_required or "medium"
            )

            # Create node
            node_data = NodeCreate(
                title=ent.title,
                node_type=ent.node_type,
                category=ent.category,
                status=ent.status,
                priority=ent.priority,
                urgency_score=priority_eval["urgency_score"],
                importance_score=priority_eval["importance_score"],
                due_date=ent.due_date,
                scheduled_start=ent.calendar_start,
                scheduled_end=ent.calendar_end,
                energy_required=ent.energy_required or "medium",
                estimated_minutes=ent.estimated_minutes or 30,
                description=ent.description or "",
                metadata={
                    "is_calendar_candidate": ent.is_calendar_candidate,
                    "clarification_needed": ent.clarification_needed,
                    "utility_score": priority_eval["utility_score"]
                }
            )

            new_node = graph_service.create_node(node_data, source_note_id=note_id, background_tasks=background_tasks)
            node_id_ref = new_node["id"]
            created_nodes_map[ent.title] = new_node
            created_nodes_map[ent.title.lower().strip()] = new_node
            created_entities.append(new_node)

            # Log decision
            decision_engine.log_decision(
                entity_id=node_id_ref,
                decision_type="PRIORITY_EVALUATION",
                rationale=f"Evaluated initial urgency ({priority_eval['urgency_score']}) and importance ({priority_eval['importance_score']}) into quadrant {priority_eval['eisenhower_quadrant']}",
                input_context={"raw_urgency": ent.urgency_score, "raw_importance": ent.importance_score, "due_date": ent.due_date},
                output_decision=priority_eval
            )

            # If clarification was flagged by LLM, generate proactive prompt
            if ent.clarification_needed:
                p_id = str(uuid.uuid4())
                title = f"Clarification: {ent.title[:25]}"
                conn = get_db_connection()
                with conn:
                    conn.execute(
                        """
                        INSERT INTO prompts_and_nudges (id, prompt_type, title, message, target_node_id, status, action_data_json, created_at)
                        VALUES (?, 'clarification', ?, ?, ?, 'active', ?, ?)
                        """,
                        (p_id, title, ent.clarification_needed, node_id_ref, json.dumps({"note_id": note_id}), utc_now_iso())
                    )
                conn.close()
                prompts_generated.append({"id": p_id, "title": title, "message": ent.clarification_needed})

            # Decision Model: Calendar Triage
            cal_decision = decision_engine.decide_calendar_action(
                node_title=ent.title,
                node_type=ent.node_type,
                is_calendar_candidate=ent.is_calendar_candidate,
                calendar_start=ent.calendar_start,
                calendar_end=ent.calendar_end,
                due_date=ent.due_date,
                estimated_minutes=ent.estimated_minutes or 30,
                quadrant=priority_eval["eisenhower_quadrant"],
                urgency=priority_eval["urgency_score"]
            )

            decision_engine.log_decision(
                entity_id=node_id_ref,
                decision_type="CALENDAR_ALLOCATION",
                rationale=cal_decision["rationale"],
                input_context={"is_candidate": ent.is_calendar_candidate, "start": ent.calendar_start, "quadrant": priority_eval["eisenhower_quadrant"]},
                output_decision=cal_decision
            )

            if cal_decision["action"] != "NONE" and req.auto_sync_calendar:
                cal_res = calendar_service.add_event(
                    node_id=node_id_ref,
                    title=cal_decision["summary"],
                    start_time_iso=cal_decision["start_time"],
                    end_time_iso=cal_decision["end_time"],
                    description=ent.description or "",
                    category=ent.category
                )
                calendar_actions.append({
                    "node_id": node_id_ref,
                    "title": ent.title,
                    "decision": cal_decision,
                    "sync_result": cal_res
                })

    # 6. Create Relationships
    for rel in extraction.relationships:
        s_key = rel.source_title.lower().strip()
        t_key = rel.target_title.lower().strip()
        source_node = (
            created_nodes_map.get(s_key)
            or created_nodes_map.get(rel.source_title)
            or graph_service.find_node_by_title_or_similarity(rel.source_title)
        )
        target_node = (
            created_nodes_map.get(t_key)
            or created_nodes_map.get(rel.target_title)
            or graph_service.find_node_by_title_or_similarity(rel.target_title)
        )

        if source_node and target_node:
            edge = graph_service.create_edge(EdgeCreate(
                source_id=source_node["id"],
                target_id=target_node["id"],
                relation_type=rel.relation_type,
                metadata={"notes": rel.context_notes or ""}
            ))
            if edge:
                created_edges.append(edge)

    # 7. Information Elicitation (Gain missing info to create proper records)
    created_elicitations = []
    for el in getattr(extraction, "elicitations", []):
        el_key = el.target_title.lower().strip()
        target = (
            created_nodes_map.get(el_key)
            or created_nodes_map.get(el.target_title)
            or graph_service.find_node_by_title_or_similarity(el.target_title)
        )
        target_id = target["id"] if target else (created_entities[0]["id"] if created_entities else None)
        target_title = target["title"] if target else el.target_title
        if target_id:
            el_id = str(uuid.uuid4())
            conn = get_db_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO elicitations (id, node_id, source_note_id, question, field_target, suggested_options_json, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (el_id, target_id, note_id, el.question, el.field_target, json.dumps(el.suggested_options), utc_now_iso())
                )
            conn.close()
            created_elicitations.append({
                "id": el_id,
                "node_id": target_id,
                "node_title": target_title,
                "question": el.question,
                "field_target": el.field_target,
                "suggested_options": el.suggested_options,
                "status": "pending"
            })
            try:
                from app.services.notification_service import notification_service
                notification_service.notify_elicitation(el.question, target_title)
            except Exception:
                pass

    # 8. People Memory & Relationship Tracking (Remembering the people involved)
    created_person_profiles = []
    for prof in getattr(extraction, "person_profiles", []):
        person_node = graph_service.find_node_by_title_or_similarity(prof.name, "person")
        if not person_node:
            person_node = graph_service.create_node(NodeCreate(
                title=prof.name,
                node_type="person",
                category="work" if prof.relationship_type in ("colleague", "manager", "client", "vendor") else "personal",
                description=f"{prof.role_or_title} at {prof.organization}".strip(" at "),
                metadata={
                    "role_or_title": prof.role_or_title,
                    "organization": prof.organization,
                    "relationship_type": prof.relationship_type
                }
            ), source_note_id=note_id)
            if not any(e["id"] == person_node["id"] for e in created_entities):
                created_entities.append(person_node)
        else:
            meta = json.loads(person_node.get("metadata_json") or "{}")
            if prof.role_or_title: meta["role_or_title"] = prof.role_or_title
            if prof.organization: meta["organization"] = prof.organization
            if prof.relationship_type: meta["relationship_type"] = prof.relationship_type
            from app.models.schemas import NodeUpdate
            graph_service.update_node(person_node["id"], NodeUpdate(metadata=meta))

        # Save memory facts about this person
        if prof.key_memories_or_facts:
            conn = get_db_connection()
            with conn:
                for fact in prof.key_memories_or_facts:
                    mem_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO person_memories (id, person_node_id, memory_fact, category, source_note_id, created_at)
                        VALUES (?, ?, ?, 'general', ?, ?)
                        """,
                        (mem_id, person_node["id"], fact, note_id, utc_now_iso())
                    )
            conn.close()

        created_person_profiles.append({
            "id": person_node["id"],
            "name": prof.name,
            "role_or_title": prof.role_or_title,
            "organization": prof.organization,
            "relationship_type": prof.relationship_type,
            "memories": prof.key_memories_or_facts
        })

    # 9. Update raw_note status
    extracted_ids = [n["id"] for n in created_entities]
    conn = get_db_connection()
    with conn:
        conn.execute(
            "UPDATE raw_notes SET processed = 1, extracted_node_ids = ? WHERE id = ?",
            (json.dumps(extracted_ids), note_id)
        )
    conn.close()

    # 9. Review Workload Capacity and Check for Overload Risk
    workload_risk = None
    created_obligations = [e for e in created_entities if e.get("node_type") == "obligation"]
    if created_obligations:
        workload_risk = decision_engine.review_workload_capacity(new_obligation=created_obligations[0])
    elif created_entities:
        workload_risk = decision_engine.review_workload_capacity(new_obligation=None)

    # 10. Background sweep for graph hygiene
    background_tasks.add_task(decision_engine.run_proactive_prompt_sweep)

    return NoteCaptureResponse(
        note_id=note_id,
        summary=extraction.summary,
        triage_reasoning=extraction.triage_reasoning,
        created_entities=created_entities,
        created_relationships=created_edges,
        calendar_actions=calendar_actions,
        prompts_generated=prompts_generated,
        elicitations=created_elicitations,
        people_profiles=created_person_profiles,
        workload_risk=workload_risk
    )

@router.post("/upload-audio", response_model=NoteCaptureResponse)
async def upload_audio_memo(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    Ingest voice memo directly using Gemini 3.8 Flash multimodal audio support.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    content_bytes = await file.read()
    if len(content_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    # Save to uploads dir
    audio_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = settings.uploads_dir / audio_filename
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    mime_type = file.content_type or "audio/webm"

    note_id = str(uuid.uuid4())
    now = utc_now_iso()

    # 1. Save raw audio note (encrypted at rest)
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO raw_notes (id, content, source_type, audio_path, processed, created_at)
            VALUES (?, ?, 'audio', ?, 0, ?)
            """,
            (note_id, crypto_service.encrypt(f"Voice Memo: {file.filename}"), str(file_path), now)
        )
    conn.close()

    # Ingest directly with Gemini
    existing_nodes = graph_service.get_all_nodes()
    extraction = gemini_service.extract_from_note(
        note_content="",
        existing_nodes_context=existing_nodes,
        audio_bytes=content_bytes,
        audio_mime_type=mime_type
    )

    # Process entities and relationships using same pipeline
    created_nodes_map = {}
    created_entities = []
    created_edges = []
    calendar_actions = []
    prompts_generated = []

    for ent in extraction.entities:
        priority_eval = decision_engine.evaluate_obligation_priority(
            base_urgency=ent.urgency_score,
            base_importance=ent.importance_score,
            due_date=ent.due_date,
            category=ent.category,
            energy_required=ent.energy_required or "medium"
        )

        node_data = NodeCreate(
            title=ent.title,
            node_type=ent.node_type,
            category=ent.category,
            status=ent.status,
            priority=ent.priority,
            urgency_score=priority_eval["urgency_score"],
            importance_score=priority_eval["importance_score"],
            due_date=ent.due_date,
            scheduled_start=ent.calendar_start,
            scheduled_end=ent.calendar_end,
            energy_required=ent.energy_required or "medium",
            estimated_minutes=ent.estimated_minutes or 30,
            description=ent.description or "",
            metadata={"source_audio": file.filename}
        )

        new_node = graph_service.create_node(node_data, source_note_id=note_id)
        node_id_ref = new_node["id"]
        created_nodes_map[ent.title] = new_node
        created_entities.append(new_node)

        # Calendar check
        cal_decision = decision_engine.decide_calendar_action(
            node_title=ent.title,
            node_type=ent.node_type,
            is_calendar_candidate=ent.is_calendar_candidate,
            calendar_start=ent.calendar_start,
            calendar_end=ent.calendar_end,
            due_date=ent.due_date,
            estimated_minutes=ent.estimated_minutes or 30,
            quadrant=priority_eval["eisenhower_quadrant"]
        )

        if cal_decision["action"] != "NONE":
            cal_res = calendar_service.add_event(
                node_id=node_id_ref,
                title=cal_decision["summary"],
                start_time_iso=cal_decision["start_time"],
                end_time_iso=cal_decision["end_time"],
                description=ent.description or "",
                category=ent.category
            )
            calendar_actions.append({
                "node_id": node_id_ref,
                "title": ent.title,
                "decision": cal_decision,
                "sync_result": cal_res
            })

    for rel in extraction.relationships:
        source_node = created_nodes_map.get(rel.source_title) or graph_service.find_node_by_title_or_similarity(rel.source_title)
        target_node = created_nodes_map.get(rel.target_title) or graph_service.find_node_by_title_or_similarity(rel.target_title)
        if source_node and target_node:
            edge = graph_service.create_edge(EdgeCreate(
                source_id=source_node["id"],
                target_id=target_node["id"],
                relation_type=rel.relation_type,
                metadata={"notes": rel.context_notes or ""}
            ))
            if edge:
                created_edges.append(edge)

    # Elicitation & People profiles for voice memo
    created_elicitations = []
    for el in getattr(extraction, "elicitations", []):
        target = created_nodes_map.get(el.target_title) or graph_service.find_node_by_title_or_similarity(el.target_title)
        target_id = target["id"] if target else (created_entities[0]["id"] if created_entities else None)
        target_title = target["title"] if target else el.target_title
        if target_id:
            el_id = str(uuid.uuid4())
            conn = get_db_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO elicitations (id, node_id, source_note_id, question, field_target, suggested_options_json, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (el_id, target_id, note_id, el.question, el.field_target, json.dumps(el.suggested_options), utc_now_iso())
                )
            conn.close()
            created_elicitations.append({
                "id": el_id,
                "node_id": target_id,
                "node_title": target_title,
                "question": el.question,
                "field_target": el.field_target,
                "suggested_options": el.suggested_options,
                "status": "pending"
            })
            try:
                from app.services.notification_service import notification_service
                notification_service.notify_elicitation(el.question, target_title)
            except Exception:
                pass

    created_person_profiles = []
    for prof in getattr(extraction, "person_profiles", []):
        person_node = graph_service.find_node_by_title_or_similarity(prof.name, "person")
        if not person_node:
            person_node = graph_service.create_node(NodeCreate(
                title=prof.name,
                node_type="person",
                category="work" if prof.relationship_type in ("colleague", "manager", "client", "vendor") else "personal",
                description=f"{prof.role_or_title} at {prof.organization}".strip(" at "),
                metadata={
                    "role_or_title": prof.role_or_title,
                    "organization": prof.organization,
                    "relationship_type": prof.relationship_type
                }
            ), source_note_id=note_id)
            if not any(e["id"] == person_node["id"] for e in created_entities):
                created_entities.append(person_node)
        if prof.key_memories_or_facts:
            conn = get_db_connection()
            with conn:
                for fact in prof.key_memories_or_facts:
                    mem_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO person_memories (id, person_node_id, memory_fact, category, source_note_id, created_at)
                        VALUES (?, ?, ?, 'general', ?, ?)
                        """,
                        (mem_id, person_node["id"], fact, note_id, utc_now_iso())
                    )
            conn.close()

        created_person_profiles.append({
            "id": person_node["id"],
            "name": prof.name,
            "role_or_title": prof.role_or_title,
            "organization": prof.organization,
            "relationship_type": prof.relationship_type,
            "memories": prof.key_memories_or_facts
        })

    # Mark raw note processed
    extracted_ids = [n["id"] for n in created_entities]
    conn = get_db_connection()
    with conn:
        conn.execute(
            "UPDATE raw_notes SET processed = 1, extracted_node_ids = ?, content = ? WHERE id = ?",
            (json.dumps(extracted_ids), crypto_service.encrypt(f"Voice Memo: {extraction.summary}"), note_id)
        )
    conn.close()

    # Review Workload Capacity and Check for Overload Risk
    workload_risk = None
    created_obligations = [e for e in created_entities if e.get("node_type") == "obligation"]
    if created_obligations:
        workload_risk = decision_engine.review_workload_capacity(new_obligation=created_obligations[0])
    elif created_entities:
        workload_risk = decision_engine.review_workload_capacity(new_obligation=None)

    background_tasks.add_task(decision_engine.run_proactive_prompt_sweep)

    return NoteCaptureResponse(
        note_id=note_id,
        summary=extraction.summary,
        triage_reasoning=extraction.triage_reasoning,
        created_entities=created_entities,
        created_relationships=created_edges,
        calendar_actions=calendar_actions,
        prompts_generated=prompts_generated,
        elicitations=created_elicitations,
        people_profiles=created_person_profiles,
        workload_risk=workload_risk
    )

@router.get("/history")
async def list_note_history(limit: int = 30):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM raw_notes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["content"] = crypto_service.decrypt(d.get("content")) or ""
        results.append(d)
    return results

@router.get("/recent")
async def get_recent_ingestions(limit: int = 10):
    """
    Retrieve recently ingested notes with their extracted entities and pending elicitations
    so the web UI can populate the recent activity feed immediately on load/refresh.
    """
    conn = get_db_connection()
    raw_notes = conn.execute(
        "SELECT * FROM raw_notes ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()

    results = []
    for rn in raw_notes:
        note_dict = dict(rn)
        note_dict["content"] = crypto_service.decrypt(note_dict.get("content")) or ""
        note_id = note_dict["id"]
        # Find nodes originating from this note
        nodes = conn.execute(
            "SELECT * FROM nodes WHERE json_extract(metadata_json, '$.source_note_id') = ? ORDER BY created_at ASC",
            (note_id,)
        ).fetchall()
        entities = []
        for n in nodes:
            nd = dict(n)
            nd["title"] = crypto_service.decrypt(nd.get("title")) or ""
            nd["description"] = crypto_service.decrypt(nd.get("description")) or ""
            entities.append(nd)
        note_dict["created_entities"] = entities

        # Find elicitations for these nodes
        node_ids = [n["id"] for n in nodes]
        elicitations = []
        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            el_rows = conn.execute(
                f"SELECT e.*, n.title as node_title FROM elicitations e JOIN nodes n ON e.node_id = n.id WHERE e.node_id IN ({placeholders}) AND e.status = 'pending'",
                node_ids
            ).fetchall()
            for er in el_rows:
                ed = dict(er)
                ed["suggested_options"] = json.loads(ed.get("suggested_options_json") or "[]")
                elicitations.append(ed)
        note_dict["elicitations"] = elicitations
        results.append(note_dict)

    conn.close()
    return results
