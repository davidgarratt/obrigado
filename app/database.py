import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import settings

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_db_connection()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            node_type TEXT NOT NULL,
            category TEXT DEFAULT 'work',
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            urgency_score REAL DEFAULT 0.5,
            importance_score REAL DEFAULT 0.5,
            eisenhower_quadrant TEXT DEFAULT 'Q2_SCHEDULE',
            due_date TEXT,
            scheduled_start TEXT,
            scheduled_end TEXT,
            calendar_event_id TEXT,
            calendar_sync_status TEXT DEFAULT 'none',
            energy_required TEXT DEFAULT 'medium',
            estimated_minutes INTEGER DEFAULT 30,
            description TEXT,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
        CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
        CREATE INDEX IF NOT EXISTS idx_nodes_due ON nodes(due_date);
        CREATE INDEX IF NOT EXISTS idx_nodes_quadrant ON nodes(eisenhower_quadrant);

        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE,
            UNIQUE(source_id, target_id, relation_type)
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation_type);

        CREATE TABLE IF NOT EXISTS raw_notes (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'text',
            audio_path TEXT,
            processed INTEGER DEFAULT 0,
            extracted_node_ids TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            node_id TEXT PRIMARY KEY,
            vector_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS daily_summaries (
            id TEXT PRIMARY KEY,
            summary_date TEXT NOT NULL,
            summary_type TEXT NOT NULL,
            content_markdown TEXT NOT NULL,
            metrics_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_summaries_date ON daily_summaries(summary_date, summary_type);

        CREATE TABLE IF NOT EXISTS briefing_prompt_configs (
            briefing_type TEXT PRIMARY KEY,
            tone_directive TEXT DEFAULT '',
            custom_instructions TEXT DEFAULT '',
            full_template TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prompts_and_nudges (
            id TEXT PRIMARY KEY,
            prompt_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            target_node_id TEXT,
            status TEXT DEFAULT 'active',
            action_data_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_prompts_status ON prompts_and_nudges(status);

        CREATE TABLE IF NOT EXISTS decision_logs (
            id TEXT PRIMARY KEY,
            entity_id TEXT,
            decision_type TEXT NOT NULL,
            rationale TEXT NOT NULL,
            input_context_json TEXT DEFAULT '{}',
            output_decision_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS elicitations (
            id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            source_note_id TEXT,
            question TEXT NOT NULL,
            field_target TEXT NOT NULL,
            suggested_options_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            user_response TEXT,
            created_at TEXT NOT NULL,
            answered_at TEXT,
            FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_elicitations_status ON elicitations(status);
        CREATE INDEX IF NOT EXISTS idx_elicitations_node ON elicitations(node_id);

        CREATE TABLE IF NOT EXISTS person_memories (
            id TEXT PRIMARY KEY,
            person_node_id TEXT NOT NULL,
            memory_fact TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            source_note_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (person_node_id) REFERENCES nodes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_person_memories_node ON person_memories(person_node_id);

        CREATE TABLE IF NOT EXISTS token_usage_logs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0.0,
            metadata_json TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_token_usage_activity ON token_usage_logs(activity_type);
        CREATE INDEX IF NOT EXISTS idx_token_usage_provider ON token_usage_logs(provider);
        CREATE INDEX IF NOT EXISTS idx_token_usage_model ON token_usage_logs(model);

        CREATE TABLE IF NOT EXISTS model_pricing (
            model_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            display_name TEXT NOT NULL,
            input_cost_per_million REAL NOT NULL,
            output_cost_per_million REAL NOT NULL,
            is_auto_fetched INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        -- Security & Google Authentication Tables
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            picture TEXT,
            role TEXT DEFAULT 'owner',
            created_at TEXT NOT NULL,
            last_login_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);

        -- Push Notifications for Android / Pixel 10 XL (WebPush & ntfy.sh)
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id TEXT PRIMARY KEY,
            endpoint TEXT UNIQUE NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            device_name TEXT DEFAULT 'Pixel 10 XL',
            user_agent TEXT,
            created_at TEXT NOT NULL,
            last_used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS notification_configs (
            id TEXT PRIMARY KEY DEFAULT 'default',
            webpush_enabled INTEGER DEFAULT 1,
            ntfy_enabled INTEGER DEFAULT 1,
            ntfy_topic TEXT DEFAULT 'obrigado_pixel_alerts',
            ntfy_server_url TEXT DEFAULT 'https://ntfy.sh',
            notify_on_briefing INTEGER DEFAULT 1,
            notify_on_elicitation INTEGER DEFAULT 1,
            notify_on_urgent_nudge INTEGER DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        """)

        # Seed default notification configuration if not present
        conf_count = conn.execute("SELECT COUNT(*) FROM notification_configs").fetchone()[0]
        if conf_count == 0:
            import secrets
            topic_suffix = secrets.token_hex(4)
            conn.execute("""
                INSERT OR IGNORE INTO notification_configs (
                    id, webpush_enabled, ntfy_enabled, ntfy_topic, ntfy_server_url,
                    notify_on_briefing, notify_on_elicitation, notify_on_urgent_nudge, updated_at
                ) VALUES ('default', 1, 1, ?, 'https://ntfy.sh', 1, 1, 1, ?)
            """, (f"obrigado_pixel_{topic_suffix}", utc_now_iso()))

        # Seed default model pricing if not already present
        count = conn.execute("SELECT COUNT(*) FROM model_pricing").fetchone()[0]
        if count == 0:
            now_iso = utc_now_iso()
            default_pricings = [
                ("gemini-3.8-flash", "gemini", "Gemini 3.8 Flash", 0.10, 0.40, 0, now_iso),
                ("gemini-2.0-flash", "gemini", "Gemini 2.0 Flash", 0.10, 0.40, 0, now_iso),
                ("gemini-1.5-flash", "gemini", "Gemini 1.5 Flash", 0.075, 0.30, 0, now_iso),
                ("gemini-embedding-2", "gemini", "Gemini Embedding 2", 0.02, 0.00, 0, now_iso),
                ("anthropic/claude-3.5-sonnet", "openrouter", "Claude 3.5 Sonnet", 3.00, 15.00, 0, now_iso),
                ("anthropic/claude-sonnet-5.5", "openrouter", "Claude Sonnet 5.5", 2.00, 10.00, 0, now_iso),
                ("deepseek/deepseek-r1", "openrouter", "DeepSeek R1", 0.55, 2.19, 0, now_iso),
                ("meta-llama/llama-3.3-70b-instruct", "openrouter", "Llama 3.3 70B Instruct", 0.12, 0.30, 0, now_iso),
                ("default", "custom", "Default Fallback Rate", 0.15, 0.60, 0, now_iso)
            ]
            conn.executemany(
                """
                INSERT OR IGNORE INTO model_pricing 
                (model_id, provider, display_name, input_cost_per_million, output_cost_per_million, is_auto_fetched, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                default_pricings
            )

        # Migrate existing plaintext database records to encrypted at rest format
        from app.services.crypto_service import crypto_service
        crypto_service.migrate_database(conn)

    conn.close()

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
