from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from app.services.token_service import token_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

class ModelPricingRequest(BaseModel):
    model_id: str
    provider: str = "custom"
    display_name: str
    input_cost_per_million: float
    output_cost_per_million: float

@router.get("/tokens")
async def get_token_analytics(
    timeframe: str = Query("day", description="Aggregation timeframe: day, week, month, year"),
    period: int = Query(30, description="Number of past time periods to include"),
    activity: Optional[str] = Query(None, description="Filter by activity: ingestion, summarisation, elicitation, nudge, embedding"),
    model: Optional[str] = Query(None, description="Filter by model ID"),
    provider: Optional[str] = Query(None, description="Filter by provider: gemini, openrouter, custom")
):
    """
    Retrieve token usage, estimated costs, breakdowns by activity/model/provider,
    and time series data for visual analytics charts.
    """
    if timeframe.lower() not in ("day", "week", "month", "year"):
        timeframe = "day"

    return token_service.get_token_analytics(
        timeframe=timeframe,
        period=period,
        activity=activity,
        model=model,
        provider=provider
    )

@router.get("/pricing")
async def get_model_pricings():
    """Get all configured model pricing rates."""
    return token_service.get_all_pricing()

@router.post("/pricing")
async def update_model_pricing(req: ModelPricingRequest):
    """Add or update model pricing rates (input & output cost per 1M tokens)."""
    try:
        return token_service.set_model_pricing(
            model_id=req.model_id,
            provider=req.provider,
            display_name=req.display_name,
            input_cost_per_million=req.input_cost_per_million,
            output_cost_per_million=req.output_cost_per_million,
            is_auto_fetched=False
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/pricing/{model_id:path}")
async def delete_model_pricing(model_id: str):
    """Delete a custom model pricing configuration."""
    success = token_service.delete_model_pricing(model_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Cannot delete model pricing: {model_id}")
    return {"success": True, "deleted": model_id}

@router.post("/pricing/sync-openrouter")
async def sync_openrouter_pricing():
    """Auto-fetch and update current model pricing from OpenRouter API."""
    res = token_service.fetch_openrouter_pricing()
    if not res.get("success"):
        raise HTTPException(status_code=502, detail=res.get("error", "Failed to sync pricing from OpenRouter"))
    return res
