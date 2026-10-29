from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from app.services.briefing_service import briefing_service

router = APIRouter(prefix="/api/briefings", tags=["briefings"])

class BriefingRequest(BaseModel):
    summary_type: str = "morning" # "morning", "evening", or "cto"
    target_date: Optional[str] = None

class BriefingPromptUpdateRequest(BaseModel):
    tone_directive: Optional[str] = None
    custom_instructions: Optional[str] = None
    full_template: Optional[str] = None

@router.get("/latest")
async def get_latest_briefing(summary_type: Optional[str] = Query(None)):
    briefing = briefing_service.get_latest_briefing(summary_type)
    if not briefing:
        # If no briefing exists yet, generate one right away
        t = summary_type or "morning"
        briefing = briefing_service.generate_briefing(summary_type=t)
    return briefing

@router.get("/history")
async def get_briefing_history(limit: int = 20):
    return briefing_service.get_briefing_history(limit=limit)

@router.post("/generate")
async def trigger_briefing(req: BriefingRequest):
    """Manually trigger Start-of-Day or End-of-Day summary generation."""
    try:
        res = briefing_service.generate_briefing(summary_type=req.summary_type, target_date=req.target_date)
        try:
            from app.services.notification_service import notification_service
            notification_service.notify_briefing_ready(req.summary_type, res.get("content_markdown", ""))
        except Exception:
            pass
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/prompts")
async def get_all_briefing_prompts():
    """Retrieve prompt templates and customized tone/content directives for all briefings."""
    return briefing_service.get_all_prompt_configs()

@router.get("/prompts/{summary_type}")
async def get_briefing_prompt(summary_type: str):
    """Retrieve prompt template and custom tone/content directives for a specific briefing type."""
    if summary_type not in ("morning", "evening", "cto"):
        raise HTTPException(status_code=400, detail=f"Invalid briefing type: {summary_type}")
    return briefing_service.get_prompt_config(summary_type)

@router.put("/prompts/{summary_type}")
async def update_briefing_prompt(summary_type: str, req: BriefingPromptUpdateRequest):
    """Update custom tone, focus instructions, or complete template for a briefing type."""
    try:
        return briefing_service.update_prompt_config(
            summary_type=summary_type,
            tone_directive=req.tone_directive,
            custom_instructions=req.custom_instructions,
            full_template=req.full_template
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/prompts/{summary_type}/reset")
async def reset_briefing_prompt(summary_type: str):
    """Reset a briefing prompt back to system default tone and content instructions."""
    try:
        return briefing_service.reset_prompt_config(summary_type=summary_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
