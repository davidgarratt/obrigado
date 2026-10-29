from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import NodeCreate, NodeUpdate, EdgeCreate, GraphDataResponse
from app.services.graph_service import graph_service
from app.database import get_db_connection

router = APIRouter(prefix="/api/graph", tags=["graph"])

@router.get("/network", response_model=GraphDataResponse)
async def get_graph_network(category: Optional[str] = Query(None, description="Filter by category: work, personal, etc.")):
    """Retrieve full knowledge graph data for interactive visual explorer."""
    return graph_service.get_graph_network(filter_category=category)

@router.get("/nodes")
async def list_nodes(
    node_type: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None
):
    return graph_service.get_all_nodes(node_type=node_type, status=status, category=category)

@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    node = graph_service.get_node_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found.")
    return node

@router.post("/nodes")
async def create_node(data: NodeCreate):
    created = graph_service.create_node(data)
    # If an obligation is added, review workload capacity and check for overload risk
    workload_risk = None
    if data.node_type == "obligation":
        from app.services.decision_engine import decision_engine
        workload_risk = decision_engine.review_workload_capacity(new_obligation=created)
    return {
        "node": created,
        "workload_risk": workload_risk
    }

@router.patch("/nodes/{node_id}")
async def update_node(node_id: str, data: NodeUpdate):
    updated = graph_service.update_node(node_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Node not found.")
    
    # If completed, check for unblocked dependents
    if data.status == "completed":
        unblocked = graph_service.check_unblocked_dependents(node_id)
        return {
            "node": updated,
            "unblocked_dependents": unblocked
        }

    return {"node": updated}

@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str):
    success = graph_service.delete_node(node_id)
    return {"success": success}

@router.post("/edges")
async def create_edge(edge: EdgeCreate):
    res = graph_service.create_edge(edge)
    if not res:
        raise HTTPException(status_code=400, detail="Failed to create edge.")
    return res

@router.delete("/edges/{edge_id}")
async def delete_edge(edge_id: str):
    conn = get_db_connection()
    with conn:
        conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
    conn.close()
    return {"success": True}
