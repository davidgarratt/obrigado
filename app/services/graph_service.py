import uuid
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import networkx as nx

from app.database import get_db_connection, utc_now_iso
from app.services.gemini_service import gemini_service
from app.services.crypto_service import crypto_service
from app.models.schemas import NodeCreate, NodeUpdate, EdgeCreate

logger = logging.getLogger(__name__)

class GraphService:
    def __init__(self):
        pass

    def _row_to_node(self, row: Any) -> Dict[str, Any]:
        """Convert a database row to a decrypted node dictionary."""
        if not row:
            return {}
        d = dict(row)
        d["title"] = crypto_service.decrypt(d.get("title")) or ""
        d["description"] = crypto_service.decrypt(d.get("description")) or ""
        d["metadata_json"] = crypto_service.decrypt(d.get("metadata_json")) or "{}"
        return d

    def get_all_nodes(self, node_type: Optional[str] = None, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        query = "SELECT * FROM nodes WHERE 1=1"
        params = []
        if node_type:
            query += " AND node_type = ?"
            params.append(node_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY updated_at DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._row_to_node(row) for row in rows]

    def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        conn.close()
        return self._row_to_node(row) if row else None

    def find_node_by_title_or_similarity(self, title: str, node_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Check if an entity with exact or very similar title exists.
        If not found by exact string/blind index match, uses semantic vector similarity.
        """
        clean_title = title.strip().lower()
        b_hash = crypto_service.blind_index(clean_title)
        conn = get_db_connection()

        # 1. Exact case-insensitive / blind index match
        if node_type:
            row = conn.execute(
                "SELECT * FROM nodes WHERE (title_hash = ? OR LOWER(title) = ?) AND node_type = ?",
                (b_hash, clean_title, node_type)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM nodes WHERE (title_hash = ? OR LOWER(title) = ?)",
                (b_hash, clean_title)
            ).fetchone()

        if row:
            conn.close()
            return self._row_to_node(row)

        # 2. Vector similarity search among nodes of the same type (or all if not specified)
        if gemini_service.is_configured():
            try:
                candidate_query = "SELECT n.id, n.title, n.node_type, e.vector_json FROM nodes n JOIN embeddings e ON n.id = e.node_id"
                params = []
                if node_type:
                    candidate_query += " WHERE n.node_type = ?"
                    params.append(node_type)
                
                rows = conn.execute(candidate_query, params).fetchall()
                if rows:
                    target_vec = gemini_service.generate_embedding(title)
                    best_match = None
                    highest_sim = 0.0

                    for r in rows:
                        try:
                            vec = json.loads(r["vector_json"])
                            sim = gemini_service.compute_similarity(target_vec, vec)
                            if sim > highest_sim:
                                highest_sim = sim
                                best_match = r
                        except Exception:
                            continue

                    # High confidence threshold for entity merging
                    if highest_sim >= 0.88 and best_match:
                        node_row = conn.execute("SELECT * FROM nodes WHERE id = ?", (best_match["id"],)).fetchone()
                        conn.close()
                        return self._row_to_node(node_row) if node_row else None
            except Exception as e:
                logger.warning(f"Semantic entity resolution failed: {e}")

        conn.close()
        return None

    def create_node(self, data: NodeCreate, source_note_id: Optional[str] = None, background_tasks: Optional[Any] = None) -> Dict[str, Any]:
        node_id = str(uuid.uuid4())
        now = utc_now_iso()

        # Compute quadrant from urgency and importance
        quadrant = self._calculate_quadrant(data.urgency_score, data.importance_score)

        meta = data.metadata or {}
        if source_note_id:
            meta["source_note_id"] = source_note_id

        # Encrypt sensitive fields for data at rest
        enc_title = crypto_service.encrypt(data.title)
        enc_desc = crypto_service.encrypt(data.description)
        enc_meta = crypto_service.encrypt(json.dumps(meta))
        b_hash = crypto_service.blind_index(data.title)

        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    id, title, node_type, category, status, priority,
                    urgency_score, importance_score, eisenhower_quadrant,
                    due_date, scheduled_start, scheduled_end,
                    calendar_event_id, calendar_sync_status,
                    energy_required, estimated_minutes, description,
                    metadata_json, created_at, updated_at, completed_at, title_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id, enc_title, data.node_type, data.category, data.status, data.priority,
                    data.urgency_score, data.importance_score, quadrant,
                    data.due_date, data.scheduled_start, data.scheduled_end,
                    None, "none",
                    data.energy_required, data.estimated_minutes, enc_desc,
                    enc_meta, now, now, None, b_hash
                )
            )

        conn.close()

        # Generate and save embedding in background/sync
        text_to_embed = f"{data.title} {data.description or ''}"
        if background_tasks:
            background_tasks.add_task(self._update_node_embedding, node_id, text_to_embed)
        else:
            self._update_node_embedding(node_id, text_to_embed)

        return self.get_node_by_id(node_id) # type: ignore

    def update_node(self, node_id: str, data: NodeUpdate) -> Optional[Dict[str, Any]]:
        existing = self.get_node_by_id(node_id)
        if not existing:
            return None

        now = utc_now_iso()
        fields = []
        params = []

        update_dict = data.model_dump(exclude_unset=True)

        # Recalculate quadrant if urgency or importance changes
        urgency = update_dict.get("urgency_score", existing["urgency_score"])
        importance = update_dict.get("importance_score", existing["importance_score"])
        update_dict["eisenhower_quadrant"] = self._calculate_quadrant(urgency, importance)

        # Handle completion timestamp
        if "status" in update_dict:
            if update_dict["status"] == "completed" and existing["status"] != "completed":
                update_dict["completed_at"] = now
            elif update_dict["status"] != "completed":
                update_dict["completed_at"] = None

        if "metadata" in update_dict:
            meta = json.loads(existing.get("metadata_json") or "{}")
            meta.update(update_dict.pop("metadata"))
            update_dict["metadata_json"] = json.dumps(meta)

        # Encrypt sensitive fields if updated
        if "title" in update_dict:
            raw_title = update_dict["title"]
            update_dict["title"] = crypto_service.encrypt(raw_title)
            update_dict["title_hash"] = crypto_service.blind_index(raw_title)

        if "description" in update_dict:
            update_dict["description"] = crypto_service.encrypt(update_dict["description"])

        if "metadata_json" in update_dict:
            update_dict["metadata_json"] = crypto_service.encrypt(update_dict["metadata_json"])

        for key, val in update_dict.items():
            fields.append(f"{key} = ?")
            params.append(val)

        fields.append("updated_at = ?")
        params.append(now)

        params.append(node_id)

        conn = get_db_connection()
        with conn:
            conn.execute(f"UPDATE nodes SET {', '.join(fields)} WHERE id = ?", params)
        conn.close()

        # If title or description changed, update embedding
        if "title" in update_dict or "description" in update_dict:
            new_title = update_dict.get("title", existing["title"])
            new_desc = update_dict.get("description", existing["description"])
            self._update_node_embedding(node_id, f"{new_title} {new_desc or ''}")

        return self.get_node_by_id(node_id)

    def delete_node(self, node_id: str) -> bool:
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        conn.close()
        return True

    def create_edge(self, edge: EdgeCreate) -> Optional[Dict[str, Any]]:
        edge_id = str(uuid.uuid4())
        now = utc_now_iso()
        meta_json = json.dumps(edge.metadata or {})

        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO edges (id, source_id, target_id, relation_type, weight, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (edge_id, edge.source_id, edge.target_id, edge.relation_type, edge.weight, meta_json, now)
                )
            row = conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error creating edge: {e}")
            conn.close()
            return None

    def get_all_edges(self) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        rows = conn.execute("SELECT * FROM edges").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_graph_network(self, filter_category: Optional[str] = None) -> Dict[str, Any]:
        """
        Builds graph structure formatted for Cytoscape.js or Vis.js interactive visualization.
        Enriches nodes with degree, dependent count, and project context.
        """
        nodes = self.get_all_nodes(category=filter_category)
        edges = self.get_all_edges()

        # Build NetworkX graph for analytics
        G = nx.DiGraph()
        for n in nodes:
            G.add_node(n["id"], **n)
        for e in edges:
            if G.has_node(e["source_id"]) and G.has_node(e["target_id"]):
                G.add_edge(e["source_id"], e["target_id"], relation=e["relation_type"])

        # Compute intelligent hierarchical tiers for structured graph layout
        base_type_levels = {
            "organization": 1,
            "project": 2,
            "obligation": 3,
            "event": 4,
            "reference": 4,
            "person": 5
        }
        hierarchy_levels = {n["id"]: base_type_levels.get(n["node_type"], 3) for n in nodes}
        # Refine levels for dependencies between obligations (prerequisites placed higher)
        for u, v, edata in G.edges(data=True):
            rel = edata.get("relation")
            if rel in ["DEPENDS_ON", "BLOCKS"]:
                prereq, dep = (v, u) if rel == "DEPENDS_ON" else (u, v)
                if G.has_node(prereq) and G.has_node(dep):
                    if G.nodes[prereq].get("node_type") == "obligation" and G.nodes[dep].get("node_type") == "obligation":
                        if hierarchy_levels[dep] <= hierarchy_levels[prereq]:
                            hierarchy_levels[dep] = hierarchy_levels[prereq] + 1

        node_list = []
        for n in nodes:
            nid = n["id"]
            in_degree = G.in_degree(nid) if G.has_node(nid) else 0
            out_degree = G.out_degree(nid) if G.has_node(nid) else 0

            # Count obligations that depend on this node
            blocking_count = 0
            if G.has_node(nid):
                # nodes pointing to this with DEPENDS_ON or this pointing with BLOCKS
                for u, v, data in G.in_edges(nid, data=True):
                    if data.get("relation") == "DEPENDS_ON":
                        blocking_count += 1
                for u, v, data in G.out_edges(nid, data=True):
                    if data.get("relation") == "BLOCKS":
                        blocking_count += 1

            node_data = {
                "id": n["id"],
                "title": n["title"],
                "node_type": n["node_type"],
                "category": n["category"],
                "status": n["status"],
                "priority": n["priority"],
                "urgency_score": n["urgency_score"],
                "importance_score": n["importance_score"],
                "eisenhower_quadrant": n["eisenhower_quadrant"],
                "due_date": n["due_date"],
                "scheduled_start": n["scheduled_start"],
                "calendar_sync_status": n["calendar_sync_status"],
                "description": n["description"],
                "in_degree": in_degree,
                "out_degree": out_degree,
                "blocking_count": blocking_count,
                "hierarchy_level": hierarchy_levels.get(nid, 3)
            }
            node_list.append(node_data)

        edge_list = []
        for e in edges:
            edge_list.append({
                "id": e["id"],
                "source": e["source_id"],
                "target": e["target_id"],
                "relation_type": e["relation_type"],
                "weight": e["weight"]
            })

        # Calculate project stats
        projects = [n for n in nodes if n["node_type"] == "project"]
        project_stats = []
        for p in projects:
            p_id = p["id"]
            # Find all nodes with PART_OF pointing to this project
            part_of_nodes = [
                e["source_id"] for e in edges 
                if e["target_id"] == p_id and e["relation_type"] == "PART_OF"
            ]
            total_tasks = len(part_of_nodes)
            completed_tasks = sum(
                1 for nid in part_of_nodes 
                if any(n["id"] == nid and n["status"] == "completed" for n in nodes)
            )
            pct = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0
            project_stats.append({
                "id": p_id,
                "title": p["title"],
                "category": p["category"],
                "status": p["status"],
                "total_obligations": total_tasks,
                "completed_obligations": completed_tasks,
                "progress_percent": pct
            })

        return {
            "nodes": node_list,
            "edges": edge_list,
            "stats": {
                "total_nodes": len(node_list),
                "total_edges": len(edge_list),
                "total_obligations": sum(1 for n in node_list if n["node_type"] == "obligation"),
                "pending_obligations": sum(1 for n in node_list if n["node_type"] == "obligation" and n["status"] in ("pending", "in_progress")),
                "completed_obligations": sum(1 for n in node_list if n["node_type"] == "obligation" and n["status"] == "completed"),
                "total_projects": len(projects),
                "projects": project_stats
            }
        }

    def check_unblocked_dependents(self, completed_node_id: str) -> List[Dict[str, Any]]:
        """
        When a node is marked completed, inspect all nodes that DEPENDED on it.
        If all their dependencies are now satisfied, return them as newly unblocked!
        """
        conn = get_db_connection()
        # Find all nodes that have a DEPENDS_ON edge to completed_node_id
        edges = conn.execute(
            "SELECT source_id FROM edges WHERE target_id = ? AND relation_type = 'DEPENDS_ON'",
            (completed_node_id,)
        ).fetchall()
        
        unblocked_nodes = []
        for e in edges:
            dependent_id = e["source_id"]
            # Check if this dependent node has any other unsatisfied dependencies
            other_deps = conn.execute(
                """
                SELECT n.id, n.title, n.status 
                FROM edges ed
                JOIN nodes n ON ed.target_id = n.id
                WHERE ed.source_id = ? AND ed.relation_type = 'DEPENDS_ON' AND n.status != 'completed'
                """,
                (dependent_id,)
            ).fetchall()

            if len(other_deps) == 0:
                # All dependencies are completed!
                dep_node = conn.execute("SELECT * FROM nodes WHERE id = ?", (dependent_id,)).fetchone()
                if dep_node and dep_node["status"] in ("blocked", "waiting_on", "pending"):
                    unblocked_nodes.append(dict(dep_node))
        
        conn.close()
        return unblocked_nodes

    def _calculate_quadrant(self, urgency: float, importance: float) -> str:
        """Eisenhower Matrix classification: threshold at 0.5"""
        if urgency >= 0.5 and importance >= 0.5:
            return "Q1_DO_FIRST"
        elif urgency < 0.5 and importance >= 0.5:
            return "Q2_SCHEDULE"
        elif urgency >= 0.5 and importance < 0.5:
            return "Q3_DELEGATE"
        else:
            return "Q4_DONT_DO"

    def _update_node_embedding(self, node_id: str, text: str):
        if not gemini_service.is_configured() or not text.strip():
            return
        try:
            vec = gemini_service.generate_embedding(text)
            if vec:
                conn = get_db_connection()
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO embeddings (node_id, vector_json, updated_at)
                        VALUES (?, ?, ?)
                        """,
                        (node_id, json.dumps(vec), utc_now_iso())
                    )
                conn.close()
        except Exception as e:
            logger.warning(f"Could not update node embedding for {node_id}: {e}")

graph_service = GraphService()
