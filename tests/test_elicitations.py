import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, get_db_connection
from app.models.schemas import NodeCreate
from app.services.graph_service import graph_service

@pytest.fixture(autouse=True)
def setup():
    init_db()

client = TestClient(app)

def test_elicitations_flow():
    # 1. Create a sparse obligation needing clarification
    node = graph_service.create_node(NodeCreate(
        title="Send quarterly summary",
        node_type="obligation",
        category="work",
        status="pending",
        urgency_score=0.4,
        importance_score=0.5
    ))

    # 2. Insert a pending elicitation question
    import uuid
    el_id = f"el_test_{uuid.uuid4()}"
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO elicitations (id, node_id, question, field_target, suggested_options_json, status, created_at)
            VALUES (?, ?, 'By when should the quarterly summary be sent?', 'deadline', '["Today 5pm", "Tomorrow EOD", "Next Friday"]', 'pending', '2026-10-24T12:00:00Z')
            """,
            (el_id, node["id"])
        )
    conn.close()

    # 3. Fetch pending elicitations
    res = client.get("/api/elicitations/pending")
    assert res.status_code == 200
    pending = res.json()
    assert any(e["id"] == el_id for e in pending)

    # 4. Answer the elicitation
    answer_res = client.post("/api/elicitations/answer", json={
        "elicitation_id": el_id,
        "user_answer": "Tomorrow 5pm"
    })
    assert answer_res.status_code == 200
    data = answer_res.json()
    assert data["success"] is True
    assert "updated_node" in data

    # 5. Verify elicitation is no longer pending
    res_after = client.get("/api/elicitations/pending")
    assert not any(e["id"] == el_id for e in res_after.json())
