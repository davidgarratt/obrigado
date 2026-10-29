import os
import subprocess
from typing import Optional, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from app.config import settings
from app.database import get_db_connection
from app.services.openrouter_service import openrouter_service
from app.services.migration_service import migration_service

router = APIRouter(prefix="/api/settings", tags=["settings"])

class OpenRouterConfigRequest(BaseModel):
    openrouter_api_key: str
    openrouter_model: Optional[str] = "anthropic/claude-3.5-sonnet"
    llm_provider: Optional[str] = "auto"

class BackupCreateRequest(BaseModel):
    label: Optional[str] = "manual"

@router.get("/status")
async def get_system_status():
    # Check Tailscale status if available
    tailscale_info = {"connected": False, "ips": [], "hostname": None}
    try:
        res = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            import json
            ts_data = json.loads(res.stdout)
            tailscale_info["connected"] = bool(ts_data.get("Self", {}).get("Online", False))
            tailscale_info["ips"] = ts_data.get("Self", {}).get("TailscaleIPs", [])
            tailscale_info["hostname"] = ts_data.get("Self", {}).get("HostName")
    except Exception:
        pass

    conn = get_db_connection()
    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    notes_count = conn.execute("SELECT COUNT(*) FROM raw_notes").fetchone()[0]
    conn.close()

    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "gemini_api_key_configured": bool(settings.gemini_api_key),
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "openrouter_configured": openrouter_service.is_configured(),
        "openrouter_model": settings.openrouter_model,
        "llm_provider": settings.llm_provider,
        "user_timezone": settings.user_timezone,
        "morning_briefing_time": settings.morning_briefing_time,
        "evening_briefing_time": settings.evening_briefing_time,
        "database_stats": {
            "total_nodes": node_count,
            "total_edges": edge_count,
            "raw_notes_captured": notes_count
        },
        "tailscale": tailscale_info
    }

@router.post("/openrouter")
async def configure_openrouter(req: OpenRouterConfigRequest):
    """Configure or update OpenRouter API key and preferred model."""
    settings.openrouter_api_key = req.openrouter_api_key
    if req.openrouter_model:
        settings.openrouter_model = req.openrouter_model
    if req.llm_provider:
        settings.llm_provider = req.llm_provider

    openrouter_service.update_credentials(req.openrouter_api_key, req.openrouter_model)

    # Persist to .env
    env_path = settings.base_dir / ".env"
    existing_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    updated = False
    new_lines = []
    for line in existing_lines:
        if line.startswith("OPENROUTER_API_KEY="):
            new_lines.append(f"OPENROUTER_API_KEY={req.openrouter_api_key}\n")
            updated = True
        elif line.startswith("OPENROUTER_MODEL=") and req.openrouter_model:
            new_lines.append(f"OPENROUTER_MODEL={req.openrouter_model}\n")
        elif line.startswith("LLM_PROVIDER=") and req.llm_provider:
            new_lines.append(f"LLM_PROVIDER={req.llm_provider}\n")
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"\nOPENROUTER_API_KEY={req.openrouter_api_key}\n")
        new_lines.append(f"OPENROUTER_MODEL={req.openrouter_model or 'anthropic/claude-3.5-sonnet'}\n")
        new_lines.append(f"LLM_PROVIDER={req.llm_provider or 'auto'}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return {
        "success": True,
        "openrouter_configured": openrouter_service.is_configured(),
        "openrouter_model": settings.openrouter_model,
        "llm_provider": settings.llm_provider,
        "message": "OpenRouter configuration saved successfully!"
    }

@router.post("/clear-data")
async def clear_all_sample_data():
    """Wipe all graph nodes, edges, raw notes, elicitations, and decision logs to start fresh."""
    # Automatically take a pre-wipe safety backup so nothing is permanently lost
    try:
        migration_service.create_database_backup("pre_clear_wipe")
    except Exception:
        pass

    conn = get_db_connection()
    with conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        for table in [
            "edges", "embeddings", "person_memories", "elicitations",
            "prompts_and_nudges", "decision_logs", "daily_summaries",
            "raw_notes", "nodes"
        ]:
            conn.execute(f"DELETE FROM {table};")
        conn.execute("PRAGMA foreign_keys = ON;")
    conn.close()
    return {"success": True, "message": "All database records have been cleared."}

# ==========================================
# Data Migration, Backup & Encryption Endpoints
# ==========================================

@router.get("/backup/status")
async def get_backup_status():
    """Returns database record stats, encryption health, and list of all snapshots."""
    stats = migration_service.get_database_stats()
    backups = migration_service.list_backups()
    return {
        "success": True,
        "stats": stats,
        "backups": backups
    }

@router.post("/backup/create")
async def create_backup(req: BackupCreateRequest = BackupCreateRequest()):
    """Creates an atomic SQLite database backup snapshot."""
    try:
        res = migration_service.create_database_backup(label=req.label)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup creation failed: {e}")

@router.get("/backup/export-json")
async def export_json():
    """Generates and downloads a portable decrypted JSON backup of all user data."""
    try:
        res = migration_service.export_portable_json()
        filepath = res["file_path"]
        filename = res["filename"]
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type="application/json"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

@router.post("/backup/import-json")
async def import_json(
    file: UploadFile = File(...),
    replace_existing: bool = Form(False)
):
    """Imports user data from uploaded JSON backup file and re-encrypts all sensitive fields."""
    try:
        import json
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        res = migration_service.import_portable_json(data, replace_existing=replace_existing)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {e}")

@router.post("/backup/verify")
async def verify_integrity():
    """Performs SQLite integrity check and tests 100% decryption health across all records."""
    try:
        res = migration_service.verify_database_integrity()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Integrity check failed: {e}")

@router.get("/backup/download/{filename}")
async def download_backup_file(filename: str):
    """Downloads a specific SQLite snapshot or JSON export file."""
    # Sanitize filename
    safe_name = os.path.basename(filename)
    # Search in backups_dir and data_dir
    candidate = migration_service.backups_dir / safe_name
    if not candidate.exists():
        candidate2 = settings.data_dir / safe_name
        if candidate2.exists():
            candidate = candidate2
        else:
            raise HTTPException(status_code=404, detail="Backup file not found")

    media_type = "application/json" if safe_name.endswith(".json") else "application/octet-stream"
    return FileResponse(
        path=candidate,
        filename=safe_name,
        media_type=media_type
    )

@router.post("/backup/restore/{filename}")
async def restore_backup(filename: str):
    """Restores database from an existing snapshot, automatically backing up current state first."""
    try:
        safe_name = os.path.basename(filename)
        res = migration_service.restore_database_snapshot(safe_name)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Restore failed: {e}")
