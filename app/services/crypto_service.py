import os
import hmac
import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional, Dict
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

CIPHER_PREFIX = "enc::"

class CryptoService:
    def __init__(self):
        self._key = self._resolve_or_create_key()
        self._fernet = Fernet(self._key)
        # Derive a distinct pepper for blind indexing (HMAC search)
        self._blind_index_key = hashlib.sha256(self._key + b"_obrigado_blind_index").digest()

    def _resolve_or_create_key(self) -> bytes:
        """Resolve master encryption key from settings, env, or keyfile."""
        # 1. From settings / environment
        key_str = (settings.encryption_key or os.getenv("OBRIGADO_ENCRYPTION_KEY", "")).strip()
        if key_str:
            try:
                key_bytes = key_str.encode("utf-8")
                # Validate by instantiating Fernet
                Fernet(key_bytes)
                return key_bytes
            except Exception as e:
                logger.warning(f"Invalid encryption key in environment: {e}. Falling back to keyfile.")

        # 2. From keyfile in data directory
        keyfile = settings.data_dir / ".encryption_key"
        if keyfile.exists():
            try:
                stored = keyfile.read_text(encoding="utf-8").strip()
                if stored:
                    key_bytes = stored.encode("utf-8")
                    Fernet(key_bytes)
                    return key_bytes
            except Exception as e:
                logger.warning(f"Failed to read existing keyfile: {e}. Generating new key.")

        # 3. Generate a fresh 256-bit Fernet key
        new_key = Fernet.generate_key()
        try:
            keyfile.write_text(new_key.decode("utf-8"), encoding="utf-8")
            # Try to persist to .env as well
            env_file = settings.base_dir / ".env"
            if env_file.exists():
                content = env_file.read_text(encoding="utf-8")
                if "OBRIGADO_ENCRYPTION_KEY=" not in content:
                    with open(env_file, "a", encoding="utf-8") as f:
                        f.write(f"\n# Data Encryption at Rest Master Key (Generated automatically)\nOBRIGADO_ENCRYPTION_KEY={new_key.decode('utf-8')}\n")
            logger.info("Generated new master encryption key for data at rest.")
        except Exception as e:
            logger.warning(f"Could not persist encryption key to disk: {e}")

        return new_key

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypts a plaintext string.
        Returns 'enc::<base64_ciphertext>'.
        If already encrypted or empty, returns as is.
        """
        if plaintext is None or plaintext == "":
            return plaintext
        if plaintext.startswith(CIPHER_PREFIX):
            return plaintext
        try:
            token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
            return f"{CIPHER_PREFIX}{token}"
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            return plaintext

    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        Decrypts an 'enc::<base64_ciphertext>' string.
        If plaintext (doesn't start with prefix), returns as is for backwards compatibility.
        """
        if ciphertext is None or ciphertext == "":
            return ciphertext
        if not ciphertext.startswith(CIPHER_PREFIX):
            return ciphertext
        token = ciphertext[len(CIPHER_PREFIX):]
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken:
            logger.error("Decryption failed: Invalid token or mismatched encryption key.")
            return "[Decryption Error: Key Mismatch]"
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            return ciphertext

    def encrypt_json(self, data: Any) -> str:
        """Serializes and encrypts arbitrary JSON serializable structure."""
        if data is None:
            return self.encrypt("{}") or "{}"
        try:
            raw = json.dumps(data, ensure_ascii=False)
            return self.encrypt(raw) or raw
        except Exception as e:
            logger.error(f"Failed to encrypt JSON: {e}")
            return self.encrypt(str(data)) or "{}"

    def decrypt_json(self, ciphertext: Optional[str], default: Any = None) -> Any:
        """Decrypts and parses JSON string."""
        if default is None:
            default = {}
        if not ciphertext:
            return default
        raw = self.decrypt(ciphertext)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception as e:
            logger.debug(f"JSON parse error after decrypt: {e}")
            return default

    def blind_index(self, text: Optional[str]) -> Optional[str]:
        """
        Generates a deterministic HMAC-SHA256 blind index for exact search on encrypted fields.
        Used for indexing node titles without revealing plaintext.
        """
        if text is None:
            return None
        norm = text.strip().lower()
        if not norm:
            return None
        return hmac.new(self._blind_index_key, norm.encode("utf-8"), hashlib.sha256).hexdigest()

    def migrate_database(self, conn) -> Dict[str, int]:
        """
        Migrates all existing plaintext records in SQLite to encrypted form.
        Creates backup before migrating and records migration state.
        """
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                executed_at TEXT NOT NULL
            );
            """)

        cur = conn.cursor()
        already_run = cur.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'encryption_at_rest_v1'"
        ).fetchone()

        if already_run:
            logger.debug("Database encryption at rest is already active.")
            return {"status": "already_active"}

        logger.info("Migrating database records to encrypted at rest format...")

        # 1. Create a safe backup before migration
        try:
            backup_file = settings.data_dir / f"obrigado.pre_encrypt_{int(datetime.now().timestamp())}.bak"
            if settings.db_path.exists():
                shutil.copy2(settings.db_path, backup_file)
                logger.info(f"Created pre-encryption database backup at {backup_file.name}")
        except Exception as e:
            logger.warning(f"Could not create pre-encryption backup: {e}")

        counts = {
            "nodes": 0,
            "raw_notes": 0,
            "daily_summaries": 0,
            "elicitations": 0,
            "person_memories": 0,
            "prompts_and_nudges": 0,
            "decision_logs": 0,
            "briefing_prompt_configs": 0
        }

        with conn:
            # Add title_hash column to nodes if missing
            node_cols = [c[1] for c in conn.execute("PRAGMA table_info(nodes)").fetchall()]
            if "title_hash" not in node_cols:
                conn.execute("ALTER TABLE nodes ADD COLUMN title_hash TEXT;")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_title_hash ON nodes(title_hash);")

            # 1. Encrypt nodes
            nodes_rows = conn.execute("SELECT id, title, description, metadata_json FROM nodes").fetchall()
            for r in nodes_rows:
                nid, title, desc, meta = r[0], r[1], r[2], r[3]
                title_plain = self.decrypt(title) or ""
                b_hash = self.blind_index(title_plain)
                enc_title = self.encrypt(title_plain)
                enc_desc = self.encrypt(self.decrypt(desc))
                enc_meta = self.encrypt(self.decrypt(meta))
                conn.execute(
                    "UPDATE nodes SET title = ?, description = ?, metadata_json = ?, title_hash = ? WHERE id = ?",
                    (enc_title, enc_desc, enc_meta, b_hash, nid)
                )
                counts["nodes"] += 1

            # 2. Encrypt raw_notes
            notes_rows = conn.execute("SELECT id, content FROM raw_notes").fetchall()
            for r in notes_rows:
                nid, content = r[0], r[1]
                enc_content = self.encrypt(self.decrypt(content))
                conn.execute("UPDATE raw_notes SET content = ? WHERE id = ?", (enc_content, nid))
                counts["raw_notes"] += 1

            # 3. Encrypt daily_summaries
            summary_rows = conn.execute("SELECT id, content_markdown, metrics_json FROM daily_summaries").fetchall()
            for r in summary_rows:
                sid, content_md, metrics = r[0], r[1], r[2]
                enc_md = self.encrypt(self.decrypt(content_md))
                enc_metrics = self.encrypt(self.decrypt(metrics))
                conn.execute(
                    "UPDATE daily_summaries SET content_markdown = ?, metrics_json = ? WHERE id = ?",
                    (enc_md, enc_metrics, sid)
                )
                counts["daily_summaries"] += 1

            # 4. Encrypt elicitations if table exists
            elicit_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='elicitations'").fetchone()
            if elicit_exists:
                for r in conn.execute("SELECT id, question, user_response FROM elicitations").fetchall():
                    eid, q, ans = r[0], r[1], r[2]
                    enc_q = self.encrypt(self.decrypt(q))
                    enc_ans = self.encrypt(self.decrypt(ans)) if ans else ans
                    conn.execute("UPDATE elicitations SET question = ?, user_response = ? WHERE id = ?", (enc_q, enc_ans, eid))
                    counts["elicitations"] += 1

            # 5. Encrypt person_memories if table exists
            mem_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='person_memories'").fetchone()
            if mem_exists:
                for r in conn.execute("SELECT id, memory_fact FROM person_memories").fetchall():
                    mid, fact = r[0], r[1]
                    enc_fact = self.encrypt(self.decrypt(fact))
                    conn.execute("UPDATE person_memories SET memory_fact = ? WHERE id = ?", (enc_fact, mid))
                    counts["person_memories"] += 1

            # 6. Encrypt prompts_and_nudges
            for r in conn.execute("SELECT id, title, message, action_data_json FROM prompts_and_nudges").fetchall():
                pid, p_title, p_msg, p_act = r[0], r[1], r[2], r[3]
                enc_p_title = self.encrypt(self.decrypt(p_title))
                enc_p_msg = self.encrypt(self.decrypt(p_msg))
                enc_p_act = self.encrypt(self.decrypt(p_act))
                conn.execute(
                    "UPDATE prompts_and_nudges SET title = ?, message = ?, action_data_json = ? WHERE id = ?",
                    (enc_p_title, enc_p_msg, enc_p_act, pid)
                )
                counts["prompts_and_nudges"] += 1

            # 7. Encrypt decision_logs
            for r in conn.execute("SELECT id, rationale, input_context_json FROM decision_logs").fetchall():
                did, rat, ctx = r[0], r[1], r[2]
                enc_rat = self.encrypt(self.decrypt(rat))
                enc_ctx = self.encrypt(self.decrypt(ctx))
                conn.execute(
                    "UPDATE decision_logs SET rationale = ?, input_context_json = ? WHERE id = ?",
                    (enc_rat, enc_ctx, did)
                )
                counts["decision_logs"] += 1

            # 8. Encrypt briefing_prompt_configs
            for r in conn.execute("SELECT briefing_type, custom_instructions, full_template FROM briefing_prompt_configs").fetchall():
                btype, cinst, ftmp = r[0], r[1], r[2]
                enc_cinst = self.encrypt(self.decrypt(cinst))
                enc_ftmp = self.encrypt(self.decrypt(ftmp)) if ftmp else ftmp
                conn.execute(
                    "UPDATE briefing_prompt_configs SET custom_instructions = ?, full_template = ? WHERE briefing_type = ?",
                    (enc_cinst, enc_ftmp, btype)
                )
                counts["briefing_prompt_configs"] += 1

            # Mark migration complete
            now_str = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO schema_migrations (name, executed_at) VALUES ('encryption_at_rest_v1', ?)",
                (now_str,)
            )

        logger.info(f"Database encryption migration complete. Encrypted records: {counts}")
        return counts

# Singleton instance
crypto_service = CryptoService()
