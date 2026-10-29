import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db
from app.models.schemas import NodeCreate, EdgeCreate
from app.services.graph_service import graph_service

@pytest.fixture(autouse=True)
def setup():
    init_db()

client = TestClient(app)

def test_people_memory_and_dossier():
    # 1. Create a person node: Dave
    person = graph_service.create_node(NodeCreate(
        title="Dave Miller",
        node_type="person",
        category="work",
        description="VP of Engineering at Acme",
        metadata={
            "role_or_title": "VP of Engineering",
            "organization": "Acme Corp",
            "relationship_type": "colleague"
        }
    ))
    pid = person["id"]

    # 2. Add memory facts about Dave
    res_mem1 = client.post(f"/api/people/{pid}/memories", json={
        "memory_fact": "Prefers concise Slack messages over 30-min meetings",
        "category": "preference"
    })
    assert res_mem1.status_code == 200
    mem1_id = res_mem1.json()["id"]

    res_mem2 = client.post(f"/api/people/{pid}/memories", json={
        "memory_fact": "Has two daughters: Maya and Chloe",
        "category": "personal"
    })
    assert res_mem2.status_code == 200

    # 3. Create an obligation linked to Dave via WAITING_ON
    task = graph_service.create_node(NodeCreate(
        title="PostgreSQL cluster architecture review",
        node_type="obligation",
        category="work",
        status="waiting_on",
        urgency_score=0.7,
        importance_score=0.8
    ))
    graph_service.create_edge(EdgeCreate(
        source_id=task["id"],
        target_id=pid,
        relation_type="WAITING_ON"
    ))

    # 4. Fetch all people
    res_people = client.get("/api/people")
    assert res_people.status_code == 200
    people = res_people.json()
    dave_entry = next((p for p in people if p["id"] == pid), None)
    assert dave_entry is not None
    assert len(dave_entry["memories"]) >= 2
    assert len(dave_entry["commitments_from_them"]) >= 1

    # 5. Fetch full dossier
    res_dossier = client.get(f"/api/people/{pid}")
    assert res_dossier.status_code == 200
    dossier = res_dossier.json()
    assert len(dossier["memories"]) >= 2
    assert len(dossier["obligations"]) >= 1

    # 6. Delete a memory
    del_res = client.delete(f"/api/people/memories/{mem1_id}")
    assert del_res.status_code == 200
    dossier_after = client.get(f"/api/people/{pid}").json()
    assert len(dossier_after["memories"]) == len(dossier["memories"]) - 1
