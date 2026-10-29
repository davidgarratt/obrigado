import pytest
from app.database import init_db
from app.services.graph_service import graph_service
from app.models.schemas import NodeCreate, NodeUpdate, EdgeCreate

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_node_lifecycle_and_unblocking():
    # 1. Create Prerequisite Obligation A
    node_a = graph_service.create_node(NodeCreate(
        title="Prepare Financial Ledger",
        node_type="obligation",
        category="work",
        status="pending",
        urgency_score=0.7,
        importance_score=0.8
    ))
    assert node_a["id"] is not None
    assert node_a["eisenhower_quadrant"] == "Q1_DO_FIRST"

    # 2. Create Dependent Obligation B (depends on A)
    node_b = graph_service.create_node(NodeCreate(
        title="File Q3 Corporate Tax Return",
        node_type="obligation",
        category="work",
        status="blocked",
        urgency_score=0.6,
        importance_score=0.9
    ))

    # 3. Create Edge: B depends on A
    edge = graph_service.create_edge(EdgeCreate(
        source_id=node_b["id"],
        target_id=node_a["id"],
        relation_type="DEPENDS_ON"
    ))
    assert edge is not None

    # 4. Check before completion: B is STILL BLOCKED (unblocked list should be empty)
    unblocked_before = graph_service.check_unblocked_dependents(node_a["id"])
    assert len(unblocked_before) == 0

    # 5. Mark A as completed
    updated_a = graph_service.update_node(node_a["id"], NodeUpdate(status="completed"))
    assert updated_a["status"] == "completed"
    assert updated_a["completed_at"] is not None

    # 6. Now B should be unblocked!
    unblocked_after = graph_service.check_unblocked_dependents(node_a["id"])
    assert len(unblocked_after) == 1
    assert unblocked_after[0]["id"] == node_b["id"]

    # 7. Retrieve graph network
    network = graph_service.get_graph_network()
    assert network["stats"]["total_nodes"] >= 2
    assert network["stats"]["total_edges"] >= 1
