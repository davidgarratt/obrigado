import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import httpx

from app.config import settings
from app.models.schemas import GeminiExtractionResult
from app.services.token_service import token_service

logger = logging.getLogger(__name__)

class OpenRouterService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.base_url = settings.openrouter_base_url.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def update_credentials(self, api_key: str, model: Optional[str] = None):
        self.api_key = api_key
        if model:
            self.model = model

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://obrigado.local",
            "X-Title": "Obrigado",
            "Content-Type": "application/json"
        }

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        json_mode: bool = False
    ) -> str:
        """Call OpenRouter Chat Completions endpoint."""
        if not self.is_configured():
            raise ValueError("OPENROUTER_API_KEY is not configured.")

        selected_model = model or self.model
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, headers=self._get_headers(), json=payload)
            if resp.status_code != 200:
                logger.error(f"OpenRouter API error {resp.status_code}: {resp.text}")
                resp.raise_for_status()

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise ValueError("OpenRouter returned empty choices.")

            # Record token usage
            usage = data.get("usage", {})
            prompt_tok = usage.get("prompt_tokens", 0) or 0
            comp_tok = usage.get("completion_tokens", 0) or 0
            tot_tok = usage.get("total_tokens", 0) or (prompt_tok + comp_tok)

            # Infer activity type
            act_type = "chat"
            msg_texts = " ".join(m.get("content", "") for m in messages if isinstance(m, dict)).lower()
            if "extract all distinct entities" in msg_texts:
                act_type = "ingestion"
            elif "briefing" in msg_texts or "kickoff" in msg_texts:
                act_type = "summarisation"
            elif "refine" in msg_texts or "elicitation" in msg_texts:
                act_type = "elicitation"

            token_service.record_usage(
                provider="openrouter",
                model=selected_model,
                activity_type=act_type,
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
                total_tokens=tot_tok
            )

            content = choices[0].get("message", {}).get("content", "")
            return content

    def extract_from_note(
        self,
        note_content: str,
        existing_nodes_context: List[Dict[str, Any]],
        current_time_str: Optional[str] = None
    ) -> GeminiExtractionResult:
        """Ingests note using OpenRouter LLM models (e.g. Claude 3.5 Sonnet, DeepSeek, etc.)."""
        now = current_time_str or datetime.now().astimezone().isoformat()

        context_lines = []
        if existing_nodes_context:
            context_lines.append("EXISTING GRAPH NODES (use these exact titles to link or update):")
            for node in existing_nodes_context[:50]:
                context_lines.append(f"- [{node['node_type'].upper()}] '{node['title']}' (id: {node['id']}, status: {node['status']})")

        existing_graph_str = "\n".join(context_lines) if context_lines else "No existing graph nodes yet."

        system_prompt = f"""You are the intelligence engine of Obrigado.
CURRENT LOCAL TIME: {now} (Timezone: {settings.user_timezone})

YOUR MISSION:
Extract all distinct entities, relationships, elicitation questions, and people memory profiles from the user's note.
Return a STRICT JSON object with the following schema:
{{
  "summary": "One sentence synopsis of what was understood",
  "entities": [
    {{
      "title": "Clear entity title",
      "node_type": "obligation" | "project" | "person" | "organization" | "event" | "context" | "reference",
      "category": "work" | "personal" | "health" | "admin" | "social",
      "description": "Key details and requirements",
      "status": "pending" | "in_progress" | "blocked" | "waiting_on" | "completed",
      "priority": "critical" | "high" | "medium" | "low",
      "urgency_score": 0.0 to 1.0,
      "importance_score": 0.0 to 1.0,
      "due_date": "ISO format date/datetime string or null",
      "is_calendar_candidate": true if timed event/appointment,
      "calendar_start": "ISO datetime string if calendar candidate or null",
      "calendar_end": "ISO datetime string if calendar candidate or null",
      "estimated_minutes": 30,
      "energy_required": "low" | "medium" | "high",
      "clarification_needed": "friendly question if ambiguous or null"
    }}
  ],
  "relationships": [
    {{
      "source_title": "Title of source",
      "target_title": "Title of target",
      "relation_type": "PART_OF" | "DEPENDS_ON" | "WAITING_ON" | "ASSIGNED_TO" | "INVOLVES" | "SCHEDULED_FOR" | "RELATES_TO",
      "context_notes": "optional context"
    }}
  ],
  "status_updates": [
    {{
      "target_title": "Title of existing node",
      "new_status": "completed" | "in_progress" | "blocked",
      "notes": "update notes"
    }}
  ],
  "elicitations": [
    {{
      "target_title": "Title of entity needing clarification",
      "question": "Crisp, low-friction elicitation question",
      "field_target": "deadline" | "next_action" | "project_affiliation" | "person_identity",
      "suggested_options": ["Option 1", "Option 2", "Option 3"]
    }}
  ],
  "person_profiles": [
    {{
      "name": "Full name or alias of person mentioned",
      "role_or_title": "Role or title (e.g. VP Engineering, Tax Accountant, Mom)",
      "organization": "Company or group",
      "relationship_type": "colleague" | "manager" | "client" | "family" | "friend" | "vendor",
      "key_memories_or_facts": ["1-3 key facts to remember about them"]
    }}
  ],
  "triage_reasoning": "Brief rationale of decisions made regarding urgency, importance, and calendar scheduling"
}}

Existing graph nodes:
{existing_graph_str}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"USER NOTE:\n{note_content}"}
        ]

        raw_json = self.chat_completion(messages, json_mode=True, temperature=0.1)

        try:
            # Clean markdown formatting if present
            clean_str = raw_json.strip()
            if clean_str.startswith("```json"):
                clean_str = clean_str[7:]
            if clean_str.endswith("```"):
                clean_str = clean_str[:-3]
            clean_str = clean_str.strip()

            data = json.loads(clean_str)
            return GeminiExtractionResult(**data)
        except Exception as e:
            logger.error(f"Error parsing OpenRouter response: {e}\nRaw: {raw_json}")
            raise

    def refine_node_with_elicitation(
        self,
        node: Dict[str, Any],
        question: str,
        user_answer: str,
        current_time_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """Refines a graph record based on user elicitation answer via OpenRouter."""
        now = current_time_str or datetime.now().astimezone().isoformat()
        prompt = f"""You are the record refinement agent of Obrigado.
CURRENT LOCAL TIME: {now} (Timezone: {settings.user_timezone})

CURRENT RECORD:
{json.dumps(node, indent=2, default=str)}

ELICITATION QUESTION:
"{question}"

USER RESPONSE:
"{user_answer}"

Return a JSON object with:
{{
  "title": "Refined title if needed (or keep existing)",
  "description": "Updated description incorporating the answer",
  "due_date": "Updated ISO date/datetime string if answered, or null",
  "category": "work" | "personal" | "health" | "admin" | "social",
  "priority": "critical" | "high" | "medium" | "low",
  "urgency_score": 0.0 to 1.0,
  "importance_score": 0.0 to 1.0,
  "person_role": "If person identity, their role/title",
  "person_organization": "If person identity, their organization",
  "person_relationship": "colleague" | "manager" | "client" | "friend" | "family" | "vendor",
  "memory_facts_to_save": ["List of any key facts learned about people or context"]
}}
"""
        messages = [
            {"role": "system", "content": "You are a structured data refiner that responds in valid JSON."},
            {"role": "user", "content": prompt}
        ]
        raw = self.chat_completion(messages, json_mode=True, temperature=0.2)
        try:
            clean = raw.strip()
            if clean.startswith("```json"): clean = clean[7:]
            if clean.endswith("```"): clean = clean[:-3]
            return json.loads(clean.strip())
        except Exception as e:
            logger.error(f"Failed to parse refined OpenRouter output: {e}")
            return {"description": f"{node.get('description', '')}\nClarification: {user_answer}".strip()}

openrouter_service = OpenRouterService()
