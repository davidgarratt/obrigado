import os
import json
import sqlite3
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone

from app.config import settings
from app.services.crypto_service import crypto_service, CIPHER_PREFIX
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

class MigrationService:
    def __init__(self):
        self.backups_dir = settings.data_dir / "backups"
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def _get_conn(self, db_path: Optional[Path] = None) -> sqlite3.Connection:
        target = db_path or settings.db_path
        conn = sqlite3.connect(target)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def get_database_stats(self) -> Dict[str, Any]:
        """Returns comprehensive stats on row counts, file size, and encryption health."""
        if not settings.db_path.exists():
            return {"exists": False}

        file_size = settings.db_path.stat().st_size
        conn = self._get_conn()
        cur = conn.cursor()

        tables = [
            "nodes", "edges", "raw_notes", "daily_summaries", "person_memories",
            "elicitations", "prompts_and_nudges", "decision_logs",
            "token_usage_logs", "model_pricing", "briefing_prompt_configs"
        ]

        table_counts = {}
        for t in tables:
            try:
                c = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                table_counts[t] = c
            except Exception:
                table_counts[t] = 0

        # Check migration flag
        migrated = False
        try:
            r = cur.execute("SELECT 1 FROM schema_migrations WHERE name = 'encryption_at_rest_v1'").fetchone()
            migrated = bool(r)
        except Exception:
            pass

        conn.close()

        # Format human readable size
        if file_size < 1024:
            size_fmt = f"{file_size} B"
        elif file_size < 1024 * 1024:
            size_fmt = f"{file_size / 1024:.1f} KB"
        else:
            size_fmt = f"{file_size / (1024 * 1024):.2f} MB"

        return {
            "exists": True,
            "db_path": str(settings.db_path),
            "file_size_bytes": file_size,
            "file_size_formatted": size_fmt,
            "encryption_at_rest_active": migrated,
            "encryption_algorithm": "AES-128 Fernet + HMAC-SHA256 Blind Indexing",
            "record_counts": table_counts,
            "total_entities": table_counts.get("nodes", 0),
            "total_relationships": table_counts.get("edges", 0),
            "total_notes": table_counts.get("raw_notes", 0),
            "total_memories": table_counts.get("person_memories", 0),
            "total_briefings": table_counts.get("daily_summaries", 0),
        }

    def create_database_backup(self, label: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates an atomic SQLite database backup snapshot in data/backups/.
        Forces a WAL checkpoint to ensure all data is flushed to disk.
        """
        if not settings.db_path.exists():
            raise FileNotFoundError(f"Database file not found at {settings.db_path}")

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = f"_{label.strip()}" if label else ""
        filename = f"obrigado_backup_{now_str}{safe_label}.db"
        dest_path = self.backups_dir / filename

        source_conn = sqlite3.connect(settings.db_path)
        # Flush WAL writes
        source_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

        dest_conn = sqlite3.connect(dest_path)
        try:
            with dest_conn:
                source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            source_conn.close()

        file_size = dest_path.stat().st_size
        sha256 = self._compute_sha256(dest_path)

        stats = self.get_database_stats()

        logger.info(f"Database backup created: {filename} ({file_size} bytes, sha256: {sha256[:10]}...)")
        return {
            "success": True,
            "filename": filename,
            "path": str(dest_path),
            "file_size_bytes": file_size,
            "file_size_formatted": f"{file_size / (1024 * 1024):.2f} MB",
            "sha256": sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "record_counts": stats["record_counts"]
        }

    def list_backups(self) -> List[Dict[str, Any]]:
        """Lists all database backups and JSON export snapshots."""
        backups = []
        # Check data/backups/
        for p in self.backups_dir.glob("*.*"):
            if p.suffix.lower() in (".db", ".bak", ".json"):
                backups.append(self._format_backup_file_info(p))

        # Also check existing root data/ .bak files
        for p in settings.data_dir.glob("obrigado.pre_encrypt_*.bak"):
            backups.append(self._format_backup_file_info(p, is_baseline=True))

        # Sort by mtime descending (newest first)
        backups.sort(key=lambda x: x["timestamp_epoch"], reverse=True)
        return backups

    def _format_backup_file_info(self, p: Path, is_baseline: bool = False) -> Dict[str, Any]:
        stat = p.stat()
        size = stat.st_size
        if size < 1024:
            size_fmt = f"{size} B"
        elif size < 1024 * 1024:
            size_fmt = f"{size / 1024:.1f} KB"
        else:
            size_fmt = f"{size / (1024 * 1024):.2f} MB"

        b_type = "sqlite_backup" if p.suffix.lower() in (".db", ".bak") else "json_export"
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        return {
            "filename": p.name,
            "path": str(p),
            "file_type": b_type,
            "size_bytes": size,
            "size_formatted": size_fmt,
            "modified_at": mtime,
            "timestamp_epoch": stat.st_mtime,
            "is_baseline": is_baseline or "pre_encrypt" in p.name
        }

    def export_portable_json(self, output_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """
        Exports all database entities and tables into a decrypted, portable JSON format.
        This file can be restored anywhere, regardless of encryption key or environment.
        """
        conn = self._get_conn()
        cur = conn.cursor()

        # 1. Nodes (decrypted)
        nodes = []
        for r in cur.execute("SELECT * FROM nodes").fetchall():
            row_dict = dict(r)
            row_dict["title"] = crypto_service.decrypt(row_dict.get("title"))
            row_dict["description"] = crypto_service.decrypt(row_dict.get("description"))
            # metadata_json may be encrypted or plain
            meta_raw = crypto_service.decrypt(row_dict.get("metadata_json"))
            try:
                row_dict["metadata_json"] = json.loads(meta_raw) if meta_raw else {}
            except Exception:
                row_dict["metadata_json"] = meta_raw
            # Remove title_hash from portable export as it's key-specific
            row_dict.pop("title_hash", None)
            nodes.append(row_dict)

        # 2. Edges
        edges = []
        for r in cur.execute("SELECT * FROM edges").fetchall():
            row_dict = dict(r)
            meta_raw = row_dict.get("metadata_json")
            try:
                row_dict["metadata_json"] = json.loads(meta_raw) if meta_raw else {}
            except Exception:
                pass
            edges.append(row_dict)

        # 3. Raw Notes (decrypted)
        raw_notes = []
        for r in cur.execute("SELECT * FROM raw_notes").fetchall():
            row_dict = dict(r)
            row_dict["content"] = crypto_service.decrypt(row_dict.get("content"))
            ext_ids = row_dict.get("extracted_node_ids")
            try:
                row_dict["extracted_node_ids"] = json.loads(ext_ids) if ext_ids else []
            except Exception:
                pass
            raw_notes.append(row_dict)

        # 4. Daily Summaries (decrypted)
        summaries = []
        for r in cur.execute("SELECT * FROM daily_summaries").fetchall():
            row_dict = dict(r)
            row_dict["content_markdown"] = crypto_service.decrypt(row_dict.get("content_markdown"))
            metrics_raw = crypto_service.decrypt(row_dict.get("metrics_json"))
            try:
                row_dict["metrics_json"] = json.loads(metrics_raw) if metrics_raw else {}
            except Exception:
                row_dict["metrics_json"] = metrics_raw
            summaries.append(row_dict)

        # 5. Person Memories (decrypted)
        memories = []
        try:
            for r in cur.execute("SELECT * FROM person_memories").fetchall():
                row_dict = dict(r)
                row_dict["memory_fact"] = crypto_service.decrypt(row_dict.get("memory_fact"))
                memories.append(row_dict)
        except Exception:
            pass

        # 6. Elicitations (decrypted)
        elicitations = []
        try:
            for r in cur.execute("SELECT * FROM elicitations").fetchall():
                row_dict = dict(r)
                row_dict["question"] = crypto_service.decrypt(row_dict.get("question"))
                ans = row_dict.get("user_response")
                row_dict["user_response"] = crypto_service.decrypt(ans) if ans else ans
                opts_raw = row_dict.get("suggested_options_json")
                try:
                    row_dict["suggested_options_json"] = json.loads(opts_raw) if opts_raw else []
                except Exception:
                    pass
                elicitations.append(row_dict)
        except Exception:
            pass

        # 7. Prompts and Nudges (decrypted)
        prompts = []
        try:
            for r in cur.execute("SELECT * FROM prompts_and_nudges").fetchall():
                row_dict = dict(r)
                row_dict["title"] = crypto_service.decrypt(row_dict.get("title"))
                row_dict["message"] = crypto_service.decrypt(row_dict.get("message"))
                act_raw = crypto_service.decrypt(row_dict.get("action_data_json"))
                try:
                    row_dict["action_data_json"] = json.loads(act_raw) if act_raw else {}
                except Exception:
                    row_dict["action_data_json"] = act_raw
                prompts.append(row_dict)
        except Exception:
            pass

        # 8. Decision Logs (decrypted)
        decisions = []
        try:
            for r in cur.execute("SELECT * FROM decision_logs").fetchall():
                row_dict = dict(r)
                row_dict["rationale"] = crypto_service.decrypt(row_dict.get("rationale"))
                ctx_raw = crypto_service.decrypt(row_dict.get("input_context_json"))
                try:
                    row_dict["input_context_json"] = json.loads(ctx_raw) if ctx_raw else {}
                except Exception:
                    row_dict["input_context_json"] = ctx_raw
                decisions.append(row_dict)
        except Exception:
            pass

        # 9. Briefing Prompt Configs (decrypted)
        prompt_configs = []
        try:
            for r in cur.execute("SELECT * FROM briefing_prompt_configs").fetchall():
                row_dict = dict(r)
                row_dict["custom_instructions"] = crypto_service.decrypt(row_dict.get("custom_instructions"))
                tmpl = row_dict.get("full_template")
                row_dict["full_template"] = crypto_service.decrypt(tmpl) if tmpl else tmpl
                prompt_configs.append(row_dict)
        except Exception:
            pass

        # 10. Token Usage Logs
        token_logs = []
        try:
            for r in cur.execute("SELECT * FROM token_usage_logs").fetchall():
                row_dict = dict(r)
                meta = row_dict.get("metadata_json")
                try:
                    row_dict["metadata_json"] = json.loads(meta) if meta else {}
                except Exception:
                    pass
                token_logs.append(row_dict)
        except Exception:
            pass

        # 11. Model Pricing
        pricing = []
        try:
            for r in cur.execute("SELECT * FROM model_pricing").fetchall():
                pricing.append(dict(r))
        except Exception:
            pass

        conn.close()

        export_data = {
            "_metadata": {
                "app_name": settings.app_name,
                "app_version": settings.app_version,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "format_version": "1.0",
                "counts": {
                    "nodes": len(nodes),
                    "edges": len(edges),
                    "raw_notes": len(raw_notes),
                    "daily_summaries": len(summaries),
                    "person_memories": len(memories),
                    "elicitations": len(elicitations),
                    "prompts_and_nudges": len(prompts),
                    "decision_logs": len(decisions),
                    "briefing_prompt_configs": len(prompt_configs),
                    "token_usage_logs": len(token_logs),
                    "model_pricing": len(pricing)
                }
            },
            "nodes": nodes,
            "edges": edges,
            "raw_notes": raw_notes,
            "daily_summaries": summaries,
            "person_memories": memories,
            "elicitations": elicitations,
            "prompts_and_nudges": prompts,
            "decision_logs": decisions,
            "briefing_prompt_configs": prompt_configs,
            "token_usage_logs": token_logs,
            "model_pricing": pricing
        }

        # Save to file if output_path is provided or generate default
        if output_path:
            out_file = Path(output_path)
        else:
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = self.backups_dir / f"obrigado_export_{now_str}.json"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported portable JSON backup to {out_file.name} ({out_file.stat().st_size} bytes)")
        return {
            "success": True,
            "file_path": str(out_file),
            "filename": out_file.name,
            "size_bytes": out_file.stat().st_size,
            "counts": export_data["_metadata"]["counts"],
            "data": export_data
        }

    def import_portable_json(
        self, 
        data_or_file: Union[Dict[str, Any], str, Path], 
        replace_existing: bool = False
    ) -> Dict[str, Any]:
        """
        Imports entities from a portable JSON backup file or dict.
        Automatically re-encrypts all sensitive fields with the current encryption key.
        If replace_existing is True, creates a pre-import SQLite backup before replacing.
        """
        # Load JSON if string or Path
        if isinstance(data_or_file, (str, Path)):
            p = Path(data_or_file)
            if not p.exists():
                raise FileNotFoundError(f"Backup file not found: {p}")
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        elif isinstance(data_or_file, dict):
            data = data_or_file
        else:
            raise ValueError("Expected dictionary, file path, or string JSON")

        if not isinstance(data, dict):
            raise ValueError("Invalid backup format: root must be a JSON object")

        # 1. If replacing, create safety snapshot
        if replace_existing:
            self.create_database_backup("pre_import_replace")

        conn = self._get_conn()
        imported_counts = {}

        with conn:
            conn.execute("PRAGMA foreign_keys = OFF;")

            if replace_existing:
                for tbl in [
                    "edges", "embeddings", "person_memories", "elicitations",
                    "prompts_and_nudges", "decision_logs", "daily_summaries",
                    "raw_notes", "nodes", "briefing_prompt_configs"
                ]:
                    conn.execute(f"DELETE FROM {tbl};")

            # 1. Import Nodes
            nodes = data.get("nodes", [])
            node_count = 0
            for n in nodes:
                nid = n["id"]
                title_plain = n.get("title") or ""
                b_hash = crypto_service.blind_index(title_plain)
                enc_title = crypto_service.encrypt(title_plain)
                enc_desc = crypto_service.encrypt(n.get("description"))

                meta = n.get("metadata_json")
                if isinstance(meta, dict):
                    enc_meta = crypto_service.encrypt_json(meta)
                else:
                    enc_meta = crypto_service.encrypt(str(meta or "{}"))

                conn.execute("""
                    INSERT OR REPLACE INTO nodes (
                        id, title, node_type, category, status, priority,
                        urgency_score, importance_score, eisenhower_quadrant,
                        due_date, scheduled_start, scheduled_end,
                        calendar_event_id, calendar_sync_status,
                        energy_required, estimated_minutes, description,
                        metadata_json, created_at, updated_at, completed_at, title_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    nid, enc_title, n.get("node_type", "reference"), n.get("category", "work"),
                    n.get("status", "pending"), n.get("priority", "medium"),
                    n.get("urgency_score", 0.5), n.get("importance_score", 0.5),
                    n.get("eisenhower_quadrant", "Q2_SCHEDULE"),
                    n.get("due_date"), n.get("scheduled_start"), n.get("scheduled_end"),
                    n.get("calendar_event_id"), n.get("calendar_sync_status", "none"),
                    n.get("energy_required", "medium"), n.get("estimated_minutes", 30),
                    enc_desc, enc_meta, n.get("created_at"), n.get("updated_at"),
                    n.get("completed_at"), b_hash
                ))
                node_count += 1
            imported_counts["nodes"] = node_count

            # 2. Import Edges
            edges = data.get("edges", [])
            edge_count = 0
            for e in edges:
                meta = e.get("metadata_json")
                meta_str = json.dumps(meta) if isinstance(meta, dict) else str(meta or "{}")
                conn.execute("""
                    INSERT OR REPLACE INTO edges (
                        id, source_id, target_id, relation_type, weight, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    e["id"], e["source_id"], e["target_id"],
                    e.get("relation_type", "RELATED_TO"),
                    e.get("weight", 1.0), meta_str, e.get("created_at")
                ))
                edge_count += 1
            imported_counts["edges"] = edge_count

            # 3. Import Raw Notes
            raw_notes = data.get("raw_notes", [])
            notes_count = 0
            for r in raw_notes:
                enc_content = crypto_service.encrypt(r.get("content"))
                ext_ids = r.get("extracted_node_ids")
                ext_str = json.dumps(ext_ids) if isinstance(ext_ids, list) else str(ext_ids or "[]")
                conn.execute("""
                    INSERT OR REPLACE INTO raw_notes (
                        id, content, source_type, audio_path, processed, extracted_node_ids, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["id"], enc_content, r.get("source_type", "text"),
                    r.get("audio_path"), r.get("processed", 0), ext_str, r.get("created_at")
                ))
                notes_count += 1
            imported_counts["raw_notes"] = notes_count

            # 4. Import Daily Summaries
            summaries = data.get("daily_summaries", [])
            sum_count = 0
            for s in summaries:
                enc_md = crypto_service.encrypt(s.get("content_markdown"))
                metrics = s.get("metrics_json")
                if isinstance(metrics, dict):
                    enc_metrics = crypto_service.encrypt_json(metrics)
                else:
                    enc_metrics = crypto_service.encrypt(str(metrics or "{}"))
                conn.execute("""
                    INSERT OR REPLACE INTO daily_summaries (
                        id, summary_date, summary_type, content_markdown, metrics_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    s["id"], s.get("summary_date"), s.get("summary_type", "morning"),
                    enc_md, enc_metrics, s.get("created_at")
                ))
                sum_count += 1
            imported_counts["daily_summaries"] = sum_count

            # 5. Import Person Memories
            memories = data.get("person_memories", [])
            mem_count = 0
            for m in memories:
                enc_fact = crypto_service.encrypt(m.get("memory_fact"))
                conn.execute("""
                    INSERT OR REPLACE INTO person_memories (
                        id, person_node_id, memory_fact, category, source_note_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    m["id"], m["person_node_id"], enc_fact,
                    m.get("category", "general"), m.get("source_note_id"), m.get("created_at")
                ))
                mem_count += 1
            imported_counts["person_memories"] = mem_count

            # 6. Import Elicitations
            elicitations = data.get("elicitations", [])
            el_count = 0
            for el in elicitations:
                enc_q = crypto_service.encrypt(el.get("question"))
                ans = el.get("user_response")
                enc_ans = crypto_service.encrypt(ans) if ans else ans
                opts = el.get("suggested_options_json")
                opts_str = json.dumps(opts) if isinstance(opts, list) else str(opts or "[]")
                conn.execute("""
                    INSERT OR REPLACE INTO elicitations (
                        id, node_id, source_note_id, question, field_target,
                        suggested_options_json, status, user_response, created_at, answered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    el["id"], el["node_id"], el.get("source_note_id"),
                    enc_q, el.get("field_target", "general"), opts_str,
                    el.get("status", "pending"), enc_ans,
                    el.get("created_at"), el.get("answered_at")
                ))
                el_count += 1
            imported_counts["elicitations"] = el_count

            # 7. Import Prompts and Nudges
            prompts = data.get("prompts_and_nudges", [])
            pr_count = 0
            for p_item in prompts:
                enc_p_title = crypto_service.encrypt(p_item.get("title"))
                enc_p_msg = crypto_service.encrypt(p_item.get("message"))
                act_data = p_item.get("action_data_json")
                if isinstance(act_data, dict):
                    enc_act = crypto_service.encrypt_json(act_data)
                else:
                    enc_act = crypto_service.encrypt(str(act_data or "{}"))
                conn.execute("""
                    INSERT OR REPLACE INTO prompts_and_nudges (
                        id, prompt_type, title, message, target_node_id, status, action_data_json, created_at, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p_item["id"], p_item.get("prompt_type", "nudge"),
                    enc_p_title, enc_p_msg, p_item.get("target_node_id"),
                    p_item.get("status", "active"), enc_act,
                    p_item.get("created_at"), p_item.get("resolved_at")
                ))
                pr_count += 1
            imported_counts["prompts_and_nudges"] = pr_count

            # 8. Import Decision Logs
            decisions = data.get("decision_logs", [])
            dec_count = 0
            for d in decisions:
                enc_rat = crypto_service.encrypt(d.get("rationale"))
                ctx = d.get("input_context_json")
                if isinstance(ctx, dict):
                    enc_ctx = crypto_service.encrypt_json(ctx)
                else:
                    enc_ctx = crypto_service.encrypt(str(ctx or "{}"))
                out_dec = d.get("output_decision_json")
                out_str = json.dumps(out_dec) if isinstance(out_dec, dict) else str(out_dec or "{}")
                conn.execute("""
                    INSERT OR REPLACE INTO decision_logs (
                        id, entity_id, decision_type, rationale, input_context_json, output_decision_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    d["id"], d.get("entity_id"), d.get("decision_type", "general"),
                    enc_rat, enc_ctx, out_str, d.get("created_at")
                ))
                dec_count += 1
            imported_counts["decision_logs"] = dec_count

            # 9. Import Briefing Prompt Configs
            p_configs = data.get("briefing_prompt_configs", [])
            cfg_count = 0
            for c in p_configs:
                enc_cinst = crypto_service.encrypt(c.get("custom_instructions"))
                tmpl = c.get("full_template")
                enc_tmpl = crypto_service.encrypt(tmpl) if tmpl else tmpl
                conn.execute("""
                    INSERT OR REPLACE INTO briefing_prompt_configs (
                        briefing_type, tone_directive, custom_instructions, full_template, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    c["briefing_type"], c.get("tone_directive", ""),
                    enc_cinst, enc_tmpl, c.get("updated_at")
                ))
                cfg_count += 1
            imported_counts["briefing_prompt_configs"] = cfg_count

            # 10. Import Model Pricing
            pricings = data.get("model_pricing", [])
            for pr in pricings:
                conn.execute("""
                    INSERT OR REPLACE INTO model_pricing (
                        model_id, provider, display_name, input_cost_per_million, output_cost_per_million, is_auto_fetched, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    pr["model_id"], pr["provider"], pr["display_name"],
                    pr["input_cost_per_million"], pr["output_cost_per_million"],
                    pr.get("is_auto_fetched", 0), pr["updated_at"]
                ))

            # 11. Import Token Usage Logs
            token_logs = data.get("token_usage_logs", [])
            tok_count = 0
            for tl in token_logs:
                meta = tl.get("metadata_json")
                meta_str = json.dumps(meta) if isinstance(meta, dict) else str(meta or "{}")
                conn.execute("""
                    INSERT OR REPLACE INTO token_usage_logs (
                        id, created_at, provider, model, activity_type,
                        prompt_tokens, completion_tokens, total_tokens, estimated_cost, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tl["id"], tl["created_at"], tl["provider"], tl["model"], tl["activity_type"],
                    tl.get("prompt_tokens", 0), tl.get("completion_tokens", 0),
                    tl.get("total_tokens", 0), tl.get("estimated_cost", 0.0), meta_str
                ))
                tok_count += 1
            imported_counts["token_usage_logs"] = tok_count

            conn.execute("PRAGMA foreign_keys = ON;")

        conn.close()
        logger.info(f"Imported JSON backup successfully. Counts: {imported_counts}")
        return {
            "success": True,
            "message": "Data imported and encrypted successfully.",
            "imported_counts": imported_counts
        }

    def restore_database_snapshot(self, backup_path_or_filename: str) -> Dict[str, Any]:
        """
        Restores a SQLite database snapshot.
        Takes a safety snapshot of the existing database first!
        """
        # Resolve target path
        p = Path(backup_path_or_filename)
        if not p.is_absolute():
            # Check backups dir
            candidate = self.backups_dir / backup_path_or_filename
            if candidate.exists():
                p = candidate
            else:
                candidate2 = settings.data_dir / backup_path_or_filename
                if candidate2.exists():
                    p = candidate2

        if not p.exists():
            raise FileNotFoundError(f"Backup snapshot not found: {backup_path_or_filename}")

        # Verify it's a valid SQLite DB with tables
        try:
            check_conn = sqlite3.connect(p)
            tables = [r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            check_conn.close()
            if "nodes" not in tables:
                raise ValueError(f"File {p.name} is not a valid Obrigado database (missing 'nodes' table)")
        except Exception as e:
            raise ValueError(f"Cannot restore from invalid SQLite database: {e}")

        # 1. Create safety backup of current state
        if settings.db_path.exists():
            self.create_database_backup("pre_restore")

        # 2. Restore by atomic copy or online backup
        source_conn = sqlite3.connect(p)
        dest_conn = sqlite3.connect(settings.db_path)
        try:
            with dest_conn:
                source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            source_conn.close()

        logger.info(f"Database successfully restored from snapshot: {p.name}")
        return {
            "success": True,
            "message": f"Database successfully restored from {p.name}",
            "restored_from": str(p),
            "stats": self.get_database_stats()
        }

    def verify_database_integrity(self) -> Dict[str, Any]:
        """
        Runs PRAGMA integrity_check and tests decrypting every encrypted field.
        Returns detailed decryption health and status.
        """
        if not settings.db_path.exists():
            return {"healthy": False, "error": "Database file does not exist"}

        conn = self._get_conn()
        cur = conn.cursor()

        # 1. SQLite PRAGMA check
        pragma_res = cur.execute("PRAGMA integrity_check;").fetchall()
        sqlite_ok = len(pragma_res) == 1 and pragma_res[0][0] == "ok"

        # 2. Decryption health check
        total_checked = 0
        decryption_errors = []

        # Nodes
        for r in cur.execute("SELECT id, title, description, metadata_json FROM nodes").fetchall():
            total_checked += 3
            t = crypto_service.decrypt(r["title"])
            if t and t.startswith("[Decryption Error"):
                decryption_errors.append(f"Node '{r['id']}' title decryption failed")
            d = crypto_service.decrypt(r["description"])
            if d and d.startswith("[Decryption Error"):
                decryption_errors.append(f"Node '{r['id']}' description decryption failed")
            m = crypto_service.decrypt(r["metadata_json"])
            if m and m.startswith("[Decryption Error"):
                decryption_errors.append(f"Node '{r['id']}' metadata decryption failed")

        # Raw notes
        for r in cur.execute("SELECT id, content FROM raw_notes").fetchall():
            total_checked += 1
            c = crypto_service.decrypt(r["content"])
            if c and c.startswith("[Decryption Error"):
                decryption_errors.append(f"Raw Note '{r['id']}' content decryption failed")

        # Daily summaries
        for r in cur.execute("SELECT id, content_markdown, metrics_json FROM daily_summaries").fetchall():
            total_checked += 2
            c = crypto_service.decrypt(r["content_markdown"])
            if c and c.startswith("[Decryption Error"):
                decryption_errors.append(f"Summary '{r['id']}' markdown decryption failed")
            m = crypto_service.decrypt(r["metrics_json"])
            if m and m.startswith("[Decryption Error"):
                decryption_errors.append(f"Summary '{r['id']}' metrics decryption failed")

        # Person memories
        for r in cur.execute("SELECT id, memory_fact FROM person_memories").fetchall():
            total_checked += 1
            m = crypto_service.decrypt(r["memory_fact"])
            if m and m.startswith("[Decryption Error"):
                decryption_errors.append(f"Person Memory '{r['id']}' fact decryption failed")

        # Elicitations
        for r in cur.execute("SELECT id, question, user_response FROM elicitations").fetchall():
            total_checked += 2
            q = crypto_service.decrypt(r["question"])
            if q and q.startswith("[Decryption Error"):
                decryption_errors.append(f"Elicitation '{r['id']}' question decryption failed")
            ans = r["user_response"]
            if ans:
                a = crypto_service.decrypt(ans)
                if a and a.startswith("[Decryption Error"):
                    decryption_errors.append(f"Elicitation '{r['id']}' response decryption failed")

        conn.close()

        healthy = sqlite_ok and (len(decryption_errors) == 0)

        return {
            "healthy": healthy,
            "sqlite_integrity": "ok" if sqlite_ok else str(pragma_res),
            "total_records_checked": total_checked,
            "decryption_errors_count": len(decryption_errors),
            "decryption_errors": decryption_errors[:10],
            "decryption_health_pct": 100.0 if total_checked == 0 else round((total_checked - len(decryption_errors)) / total_checked * 100, 2),
            "verified_at": datetime.now(timezone.utc).isoformat()
        }

    def rotate_encryption_key(self, new_key_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Re-encrypts all database records with a new AES-128 Fernet key.
        Takes an automatic backup first.
        Updates .encryption_key and .env.
        """
        # 1. Automatic backup
        self.create_database_backup("pre_key_rotation")

        # 2. Generate or validate new key
        if new_key_str and new_key_str.strip():
            new_key_bytes = new_key_str.strip().encode("utf-8")
            new_fernet = Fernet(new_key_bytes)
        else:
            new_key_bytes = Fernet.generate_key()
            new_fernet = Fernet(new_key_bytes)

        new_blind_key = hashlib.sha256(new_key_bytes + b"_obrigado_blind_index").digest()

        def re_encrypt(val: Optional[str]) -> Optional[str]:
            if not val:
                return val
            plain = crypto_service.decrypt(val)
            if plain is None:
                return None
            tok = new_fernet.encrypt(plain.encode("utf-8")).decode("ascii")
            return f"{CIPHER_PREFIX}{tok}"

        import hmac
        def new_blind_index(text: Optional[str]) -> Optional[str]:
            if not text:
                return None
            norm = text.strip().lower()
            if not norm:
                return None
            return hmac.new(new_blind_key, norm.encode("utf-8"), hashlib.sha256).hexdigest()

        conn = self._get_conn()
        counts = {"nodes": 0, "raw_notes": 0, "summaries": 0, "memories": 0, "elicitations": 0}

        with conn:
            # Nodes
            for r in conn.execute("SELECT id, title, description, metadata_json FROM nodes").fetchall():
                plain_title = crypto_service.decrypt(r["title"]) or ""
                b_hash = new_blind_index(plain_title)
                new_t = re_encrypt(r["title"])
                new_d = re_encrypt(r["description"])
                new_m = re_encrypt(r["metadata_json"])
                conn.execute(
                    "UPDATE nodes SET title = ?, description = ?, metadata_json = ?, title_hash = ? WHERE id = ?",
                    (new_t, new_d, new_m, b_hash, r["id"])
                )
                counts["nodes"] += 1

            # Raw notes
            for r in conn.execute("SELECT id, content FROM raw_notes").fetchall():
                new_c = re_encrypt(r["content"])
                conn.execute("UPDATE raw_notes SET content = ? WHERE id = ?", (new_c, r["id"]))
                counts["raw_notes"] += 1

            # Summaries
            for r in conn.execute("SELECT id, content_markdown, metrics_json FROM daily_summaries").fetchall():
                new_md = re_encrypt(r["content_markdown"])
                new_met = re_encrypt(r["metrics_json"])
                conn.execute("UPDATE daily_summaries SET content_markdown = ?, metrics_json = ? WHERE id = ?", (new_md, new_met, r["id"]))
                counts["summaries"] += 1

            # Person memories
            for r in conn.execute("SELECT id, memory_fact FROM person_memories").fetchall():
                new_f = re_encrypt(r["memory_fact"])
                conn.execute("UPDATE person_memories SET memory_fact = ? WHERE id = ?", (new_f, r["id"]))
                counts["memories"] += 1

            # Elicitations
            for r in conn.execute("SELECT id, question, user_response FROM elicitations").fetchall():
                new_q = re_encrypt(r["question"])
                new_a = re_encrypt(r["user_response"]) if r["user_response"] else r["user_response"]
                conn.execute("UPDATE elicitations SET question = ?, user_response = ? WHERE id = ?", (new_q, new_a, r["id"]))
                counts["elicitations"] += 1

        conn.close()

        # Update active crypto_service
        crypto_service._key = new_key_bytes
        crypto_service._fernet = new_fernet
        crypto_service._blind_index_key = new_blind_key

        # Persist new key
        new_key_str_val = new_key_bytes.decode("utf-8")
        keyfile = settings.data_dir / ".encryption_key"
        keyfile.write_text(new_key_str_val, encoding="utf-8")

        env_file = settings.base_dir / ".env"
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()
            new_lines = []
            found = False
            for line in lines:
                if line.startswith("OBRIGADO_ENCRYPTION_KEY="):
                    new_lines.append(f"OBRIGADO_ENCRYPTION_KEY={new_key_str_val}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"OBRIGADO_ENCRYPTION_KEY={new_key_str_val}")
            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        logger.info(f"Master encryption key rotated successfully. Re-encrypted records: {counts}")
        return {
            "success": True,
            "message": "Master encryption key rotated and all records re-encrypted successfully.",
            "re_encrypted_counts": counts
        }

    def _compute_sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

migration_service = MigrationService()
