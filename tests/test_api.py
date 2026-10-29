import os
os.environ["TESTING"] = "true"
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db

@pytest.fixture(autouse=True)
def setup():
    init_db()

client = TestClient(app)

def test_api_status():
    res = client.get("/api/settings/status")
    assert res.status_code == 200
    data = res.json()
    assert "app_name" in data
    assert data["app_name"] == "Obrigado"
    assert data["gemini_api_key_configured"] is True

def test_calendar_status():
    res = client.get("/api/calendar/status")
    assert res.status_code == 200
    data = res.json()
    assert "mode" in data

def test_graph_network():
    res = client.get("/api/graph/network")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert "stats" in data
    if len(data["nodes"]) > 0:
        assert "hierarchy_level" in data["nodes"][0]
        org_nodes = [n for n in data["nodes"] if n["node_type"] == "organization"]
        if org_nodes:
            assert all(n["hierarchy_level"] == 1 for n in org_nodes)
        project_nodes = [n for n in data["nodes"] if n["node_type"] == "project"]
        if project_nodes:
            assert all(n["hierarchy_level"] == 2 for n in project_nodes)

def test_eisenhower_matrix():
    res = client.get("/api/obligations/eisenhower")
    assert res.status_code == 200
    data = res.json()
    assert "Q1_DO_FIRST" in data
    assert "Q2_SCHEDULE" in data
    assert "counts" in data

def test_quick_note_ingest_with_gemini():
    # Test real end-to-end ingestion with Gemini 3.8 Flash!
    payload = {
        "content": "Dentist checkup on Tuesday at 10am at Green Street Dental. Also need to email Dave regarding Project Apollo cloud migration by Friday.",
        "source_type": "text",
        "auto_sync_calendar": True
    }
    res = client.post("/api/notes/capture", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert len(data["created_entities"]) > 0
    # Verify entities were extracted into the database
    titles = [e["title"].lower() for e in data["created_entities"]]
    assert any("dentist" in t for t in titles) or any("apollo" in t for t in titles) or any("dave" in t for t in titles)

def test_daily_briefing_generation():
    # Test on-demand briefing generation with Gemini
    payload = {
        "summary_type": "morning"
    }
    res = client.post("/api/briefings/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "content_markdown" in data
    assert len(data["content_markdown"]) > 50

def test_cto_briefing_generation():
    # Test on-demand leadership briefing generation
    payload = {
        "summary_type": "cto"
    }
    res = client.post("/api/briefings/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["summary_type"] == "cto"
    assert "content_markdown" in data
    assert len(data["content_markdown"]) > 50

def test_briefing_prompt_customization():
    # 1. Fetch all prompts
    res = client.get("/api/briefings/prompts")
    assert res.status_code == 200
    prompts = res.json()
    assert "morning" in prompts
    assert "cto" in prompts
    assert "evening" in prompts
    assert "tone_directive" in prompts["cto"]

    # 2. Update CTO prompt tone and custom instructions
    update_payload = {
        "tone_directive": "Punchy and razor sharp. High confidence.",
        "custom_instructions": "Focus heavily on automated testing velocity and commercial pipeline."
    }
    res = client.put("/api/briefings/prompts/cto", json=update_payload)
    assert res.status_code == 200
    updated = res.json()
    assert updated["tone_directive"] == update_payload["tone_directive"]
    assert updated["custom_instructions"] == update_payload["custom_instructions"]
    assert updated["is_customized"] is True

    # 3. Reset back to defaults
    res = client.post("/api/briefings/prompts/cto/reset")
    assert res.status_code == 200
    reset_data = res.json()
    assert reset_data["is_customized"] is False
    assert reset_data["custom_instructions"] == ""

def test_token_tracking_and_analytics():
    from app.services.token_service import token_service

    # 1. Record test token usages across activities & models
    token_service.record_usage(
        provider="gemini",
        model="gemini-3.8-flash",
        activity_type="ingestion",
        prompt_tokens=150,
        completion_tokens=50
    )
    token_service.record_usage(
        provider="gemini",
        model="gemini-3.8-flash",
        activity_type="summarisation",
        prompt_tokens=400,
        completion_tokens=200,
        metadata={"summary_type": "morning"}
    )
    token_service.record_usage(
        provider="openrouter",
        model="anthropic/claude-3.5-sonnet",
        activity_type="elicitation",
        prompt_tokens=300,
        completion_tokens=80
    )

    # 2. Test GET /api/analytics/tokens
    res = client.get("/api/analytics/tokens?timeframe=day")
    assert res.status_code == 200
    data = res.json()
    assert "kpis" in data
    assert data["kpis"]["today"]["total_tokens"] >= 1180
    assert data["kpis"]["today"]["total_cost"] > 0
    assert "time_series" in data
    assert len(data["time_series"]) > 0
    assert "activity_breakdown" in data
    assert any(a["activity"] == "ingestion" for a in data["activity_breakdown"])
    assert any(a["activity"] == "summarisation" for a in data["activity_breakdown"])
    assert any(a["activity"] == "elicitation" for a in data["activity_breakdown"])
    assert "model_breakdown" in data
    assert "recent_logs" in data
    assert len(data["recent_logs"]) >= 3

    # 3. Test filtering by timeframe (week, month, year)
    for tf in ("week", "month", "year"):
        r = client.get(f"/api/analytics/tokens?timeframe={tf}")
        assert r.status_code == 200

    # 4. Test filtering by activity
    r_act = client.get("/api/analytics/tokens?activity=summarisation")
    assert r_act.status_code == 200
    assert all(log["activity_type"] == "summarisation" for log in r_act.json()["recent_logs"])

    # 5. Test Model Pricing endpoints
    res_pricing = client.get("/api/analytics/pricing")
    assert res_pricing.status_code == 200
    pricings = res_pricing.json()
    assert len(pricings) >= 5

    # 6. Add/Update Custom Model Pricing
    custom_payload = {
        "model_id": "custom/test-llm-1",
        "provider": "custom",
        "display_name": "Custom Test LLM",
        "input_cost_per_million": 0.25,
        "output_cost_per_million": 1.00
    }
    res_set = client.post("/api/analytics/pricing", json=custom_payload)
    assert res_set.status_code == 200
    assert res_set.json()["model_id"] == "custom/test-llm-1"
    assert res_set.json()["input_cost_per_million"] == 0.25

    # 7. Delete custom pricing
    res_del = client.delete("/api/analytics/pricing/custom/test-llm-1")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] == "custom/test-llm-1"

def test_encryption_at_rest():
    """Verify cryptographic encryption at rest for database tables."""
    from app.services.crypto_service import crypto_service
    from app.services.graph_service import graph_service
    from app.models.schemas import NodeCreate
    from app.database import get_db_connection

    # Test basic encrypt/decrypt
    secret_text = "Confidential customer obligation for Board review"
    enc = crypto_service.encrypt(secret_text)
    assert enc.startswith("enc::")
    assert enc != secret_text
    dec = crypto_service.decrypt(enc)
    assert dec == secret_text

    # Test blind indexing
    b1 = crypto_service.blind_index("Alpha Project")
    b2 = crypto_service.blind_index("  alpha project  ")
    assert b1 == b2

    # Create node and verify encrypted storage in raw SQLite
    node_payload = NodeCreate(
        title="Encrypted Secret Task 99",
        node_type="obligation",
        category="work",
        description="Top secret contract terms with EE and BT"
    )
    created = graph_service.create_node(node_payload)
    node_id = created["id"]

    # Verify that what is written in SQLite is encrypted
    conn = get_db_connection()
    raw_row = conn.execute("SELECT title, description, title_hash FROM nodes WHERE id = ?", (node_id,)).fetchone()
    conn.close()

    assert raw_row["title"].startswith("enc::")
    assert raw_row["description"].startswith("enc::")
    assert raw_row["title_hash"] == crypto_service.blind_index("Encrypted Secret Task 99")

    # Verify that graph_service transparently decrypts
    fetched = graph_service.get_node_by_id(node_id)
    assert fetched["title"] == "Encrypted Secret Task 99"
    assert fetched["description"] == "Top secret contract terms with EE and BT"

def test_auth_and_security():
    """Verify authentication endpoints, status, and emergency login flow."""
    from app.services.auth_service import auth_service

    # 1. Check auth status endpoint
    res_status = client.get("/api/auth/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "google_configured" in data
    assert "auth_enabled" in data

    # 2. Check emergency admin token login
    token = auth_service.get_emergency_token()
    res_login = client.post("/api/auth/emergency-login", json={"token": token})
    assert res_login.status_code == 200
    assert res_login.json()["success"] is True

    # 3. Check invalid emergency login
    res_bad = client.post("/api/auth/emergency-login", json={"token": "bad_token"})
    assert res_bad.status_code == 401

    # 4. Check logout
    res_logout = client.post("/api/auth/logout")
    assert res_logout.status_code == 200
    assert res_logout.json()["success"] is True

    # 5. Check 1-Click Dev Mode Login
    from app.config import settings
    settings.dev_mode = True
    res_dev = client.post("/api/auth/dev-login")
    assert res_dev.status_code == 200
    dev_data = res_dev.json()
    assert dev_data["success"] is True
    assert dev_data["user"]["email"] == settings.dev_user_email
    assert "obrigado_session" in res_dev.cookies

    # 6. Check Dev Mode Disabled in Production
    settings.dev_mode = False
    res_dev_disabled = client.post("/api/auth/dev-login")
    assert res_dev_disabled.status_code == 403
    settings.dev_mode = True  # reset back

def test_unauthenticated_requests_blocked():
    """Verify that unauthenticated API calls return 401 and pages redirect to /login."""
    old_val = os.environ.get("TESTING")
    try:
        os.environ.pop("TESTING", None)
        unauth_client = TestClient(app)
        res_api = unauth_client.get("/api/graph/network")
        assert res_api.status_code == 401
        assert "Authentication required" in res_api.json()["detail"]

        res_page = unauth_client.get("/", follow_redirects=False)
        assert res_page.status_code == 302
        assert res_page.headers["location"] == "/login"

        # Public login page is accessible without authentication
        res_login = unauth_client.get("/login")
        assert res_login.status_code == 200
    finally:
        if old_val is not None:
            os.environ["TESTING"] = old_val

def test_backup_and_migration_api():
    """Verify database backup creation, portable JSON export, and integrity verification."""
    # 1. Status check
    res_status = client.get("/api/settings/backup/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert data["success"] is True
    assert "stats" in data
    assert "backups" in data
    assert data["stats"]["encryption_at_rest_active"] is True

    # 2. Create backup snapshot
    res_create = client.post("/api/settings/backup/create", json={"label": "pytest_unit"})
    assert res_create.status_code == 200
    create_data = res_create.json()
    assert create_data["success"] is True
    assert "pytest_unit" in create_data["filename"]
    assert "sha256" in create_data

    # 3. Verify integrity check
    res_verify = client.post("/api/settings/backup/verify")
    assert res_verify.status_code == 200
    verify_data = res_verify.json()
    assert verify_data["healthy"] is True
    assert verify_data["decryption_errors_count"] == 0
    assert verify_data["decryption_health_pct"] == 100.0

    # 4. Export portable JSON
    res_export = client.get("/api/settings/backup/export-json")
    assert res_export.status_code == 200
    assert res_export.headers["content-type"] == "application/json"
    assert "attachment" in res_export.headers.get("content-disposition", "")
    content = res_export.json()
    assert "_metadata" in content
    assert "nodes" in content
    assert "raw_notes" in content
    assert "daily_summaries" in content

def test_notifications_api():
    """Verify Android phone notification channels, VAPID WebPush subscription, and test dispatch."""
    # 1. Check notification config endpoint
    res = client.get("/api/notifications/config")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "vapid_public_key" in data
    assert len(data["vapid_public_key"]) > 50
    assert "config" in data

    # 2. Subscribe simulated Pixel 10 XL
    sub_payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/fake_pixel_token_123",
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9AcPP313T59P1W6SlPD1tETlqVC0CQNSc2Av996A1vQDQI",
            "auth": "tBHItJI5svbpez7KI4CCXg"
        },
        "device_name": "Pixel 10 XL"
    }
    res_sub = client.post("/api/notifications/subscribe", json=sub_payload)
    assert res_sub.status_code == 200
    assert res_sub.json()["success"] is True

    # 3. Verify device is registered
    res_check = client.get("/api/notifications/config")
    subs = res_check.json()["subscriptions"]
    assert any(s["device_name"] == "Pixel 10 XL" for s in subs)

    # 4. Test notification dispatch
    res_test = client.post("/api/notifications/test", json={"device_name": "Pixel 10 XL"})
    assert res_test.status_code == 200
    test_data = res_test.json()
    assert test_data["success"] is True
    assert "results" in test_data

    # 5. Unsubscribe
    res_unsub = client.post("/api/notifications/unsubscribe", json={"endpoint": sub_payload["endpoint"]})
    assert res_unsub.status_code == 200
    assert res_unsub.json()["success"] is True

    # 6. Verify Service Worker and Manifest endpoints
    res_sw = client.get("/sw.js")
    assert res_sw.status_code == 200
    assert "serviceWorker" in res_sw.text or "push" in res_sw.text

    res_mf = client.get("/manifest.json")
    assert res_mf.status_code == 200
    assert res_mf.json()["name"] == "Obrigado · Personal Assistant"

def test_workload_capacity_review():
    # 1. Fetch workload capacity on demand
    res_cap = client.get("/api/obligations/workload-capacity")
    assert res_cap.status_code == 200
    cap_data = res_cap.json()
    assert "risk_level" in cap_data
    assert "stress_score" in cap_data
    assert "total_active_obligations" in cap_data
    assert "q1_urgent_count" in cap_data
    assert "colliding_deadlines_count" in cap_data
    assert "estimated_focus_hours" in cap_data
    assert isinstance(cap_data["recommendations"], list)

    # 2. Add an urgent obligation node via API and verify capacity evaluation
    from datetime import datetime, timezone
    today_iso = datetime.now(timezone.utc).date().isoformat()
    node_payload = {
        "title": "URGENT: Critical Production Security Vulnerability Patch",
        "description": "Must patch CVE vulnerability immediately on production gateway before close of business",
        "node_type": "obligation",
        "category": "work",
        "urgency_score": 9,
        "importance_score": 9,
        "due_date": f"{today_iso}T17:00:00Z",
        "estimated_minutes": 180,
        "energy_required": "high"
    }
    res_node = client.post("/api/graph/nodes", json=node_payload)
    assert res_node.status_code == 200
    node_data = res_node.json()
    assert "workload_risk" in node_data
    assert node_data["workload_risk"] is not None
    assert "risk_level" in node_data["workload_risk"]
    assert "stress_score" in node_data["workload_risk"]

    # 3. Verify prompts or decision logs were generated
    from app.database import get_db_connection
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, prompt_type, message, status FROM prompts_and_nudges WHERE prompt_type = 'workload_overload_risk' ORDER BY created_at DESC LIMIT 1")
    prompt = c.fetchone()
    c.execute("SELECT id, decision_type, rationale FROM decision_logs WHERE decision_type = 'WORKLOAD_CAPACITY_REVIEW' ORDER BY created_at DESC LIMIT 1")
    decision = c.fetchone()
    conn.close()

    assert decision is not None
    assert "WORKLOAD_CAPACITY_REVIEW" in decision["decision_type"]
    assert prompt is not None
    assert "overload" in prompt["prompt_type"]





