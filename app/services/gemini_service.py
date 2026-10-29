import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

from google import genai
from google.genai import types
from app.config import settings
from app.models.schemas import GeminiExtractionResult
from app.services.openrouter_service import openrouter_service
from app.services.token_service import token_service

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.llm_model = settings.llm_model
        self.embedding_model = settings.embedding_model
        self._client: Optional[genai.Client] = None
        self._embedding_cache: Dict[str, List[float]] = {}

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured. Please set it in .env or settings.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for a text using Gemini embedding model."""
        if not self.is_configured() or not text.strip():
            return [0.0] * 768  # Fallback zero vector

        cache_key = text.strip()
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        try:
            res = self.client.models.embed_content(
                model=self.embedding_model,
                contents=text
            )
            if res.embeddings and len(res.embeddings) > 0:
                vec = res.embeddings[0].values
                self._embedding_cache[cache_key] = vec
                est_tokens = max(1, int(len(text) / 4))
                token_service.record_usage(
                    provider="gemini",
                    model=self.embedding_model,
                    activity_type="embedding",
                    prompt_tokens=est_tokens,
                    completion_tokens=0,
                    total_tokens=est_tokens,
                    metadata={"text_len": len(text)}
                )
                return vec
            return []
        except Exception as e:
            logger.warning(f"Error generating embedding with {self.embedding_model}: {e}")
            try:
                # Fallback to gemini-embedding-001
                res = self.client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text
                )
                if res.embeddings and len(res.embeddings) > 0:
                    vec = res.embeddings[0].values
                    self._embedding_cache[cache_key] = vec
                    return vec
            except Exception as e2:
                logger.error(f"Fallback embedding failed: {e2}")
            return []

    def compute_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        v1 = np.array(vec1, dtype=np.float32)
        v2 = np.array(vec2, dtype=np.float32)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))

    def extract_from_note(
        self,
        note_content: str,
        existing_nodes_context: List[Dict[str, Any]],
        audio_bytes: Optional[bytes] = None,
        audio_mime_type: Optional[str] = None,
        current_time_str: Optional[str] = None
    ) -> GeminiExtractionResult:
        """
        Ingests raw note (text and/or audio) and turns it into a graph of obligations,
        projects, people, dependencies, and decision assessments.
        """
        # Check if OpenRouter is configured and preferred for text extraction
        if (not audio_bytes and 
            openrouter_service.is_configured() and 
            settings.llm_provider in ("openrouter", "hybrid", "auto")):
            try:
                logger.info(f"Using OpenRouter model ({openrouter_service.model}) for note extraction.")
                return openrouter_service.extract_from_note(
                    note_content=note_content,
                    existing_nodes_context=existing_nodes_context,
                    current_time_str=current_time_str
                )
            except Exception as e:
                logger.warning(f"OpenRouter extraction failed, falling back to Gemini: {e}")

        now = current_time_str or datetime.now().astimezone().isoformat()

        # Build compact context of existing graph nodes to facilitate linking
        context_lines = []
        if existing_nodes_context:
            context_lines.append("EXISTING KNOWLEDGE GRAPH NODES (use these exact titles to link or update where relevant):")
            for node in existing_nodes_context[:50]:
                context_lines.append(f"- [{node['node_type'].upper()}] '{node['title']}' (id: {node['id']}, status: {node['status']})")

        existing_graph_str = "\n".join(context_lines) if context_lines else "No existing graph nodes yet."

        system_instruction = f"""You are the core intelligence of Obrigado - a Personal Assistant that helps an executive/developer manage cognitive load, remember obligations, track projects, and keep a clean graph of commitments.

CURRENT LOCAL TIME: {now} (Timezone: {settings.user_timezone})

YOUR MISSION:
1. Ingest the user's quick note (which could be a raw brain dump, voice memo transcription, meeting notes, or fleeting thought).
2. Extract all distinct entities:
   - 'obligation': Specific actionable commitment, task, or duty (e.g., 'Submit quarterly VAT return', 'Review Dave's PR', 'Buy mom flowers').
   - 'project': Umbrella project or initiative (e.g., 'Q3 Tax Filing', 'Apollo Migration', 'Mom's Birthday', 'Home Roof Repair').
   - 'person': Colleague, client, friend, doctor (e.g., 'Dave', 'Sarah', 'Dr. Green').
   - 'organization': Company, service, vendor, department (e.g., 'Tailscale', 'HMRC', 'Acme Corp').
   - 'event': Explicit scheduled event/appointment with specific time (e.g., 'Dentist appointment Tuesday 10am', 'Board meeting Friday 2pm').
   - 'context': Tags like #errands, #deepwork, @phone.
   - 'reference': Non-actionable info or insight to remember.

3. Extract relationships between entities:
   - 'PART_OF': Obligation is part of a Project.
   - 'DEPENDS_ON': Obligation A cannot start until Obligation B is done.
   - 'WAITING_ON': Obligation is waiting on a Person or Organization (e.g., waiting for Dave's feedback).
   - 'ASSIGNED_TO': Obligation is delegated or assigned to a Person.
   - 'INVOLVES': Stakeholder relation.
   - 'SCHEDULED_FOR': Obligation/Event scheduled for a specific date/time.

4. Apply Decision Model Analysis for each obligation:
   - 'urgency_score' (0.0 to 1.0): Proximity to deadline, explicit urgency words ('urgent', 'asap', 'today').
   - 'importance_score' (0.0 to 1.0): Career impact, financial stakes, promises made to family/superiors, core strategic value.
   - 'is_calendar_candidate': True IF:
     a) It is a fixed timed event/appointment (dentist, call, meeting).
     b) It has a hard specific deadline with a concrete hour.
     c) It is a major Q1 high-importance deep work block needing dedicated time on Google Calendar.
   - If calendar candidate, compute exact ISO 'calendar_start' and 'calendar_end' based on the CURRENT LOCAL TIME ({now}).
   - If relative dates are mentioned ('tomorrow at 3pm', 'Friday noon', 'in 3 days'), calculate exact timestamps.
   - If an obligation has ambiguous requirements, populate 'clarification_needed' with a friendly question.

5. Information Elicitation (Crucial for Incomplete Records):
   - If an obligation is missing a clear timeline/deadline, immediate next physical action, definition of done, or project context, generate an item in 'elicitations' with:
     - 'target_title': The entity's title.
     - 'question': Crisp, low-friction question (e.g. 'By when should this be done?', 'Is this for Work or Personal?').
     - 'field_target': 'deadline', 'next_action', 'project_affiliation', or 'definition_of_done'.
     - 'suggested_options': 2 to 4 quick, 1-click selectable options (e.g. ['Today EOD', 'Tomorrow 5pm', 'By Friday', 'No strict deadline']).

6. People Memory & Relationship Tracking (Crucial for remembering people):
   - For ANY person mentioned in the note, populate 'person_profiles':
     - 'name': Full name or alias.
     - 'role_or_title': Inferred or stated role (e.g. 'VP of Infrastructure', 'Tax Accountant', 'Dentist', 'Cousin').
     - 'organization': Company/group if known.
     - 'relationship_type': 'colleague', 'manager', 'direct_report', 'client', 'family', 'friend', or 'vendor'.
     - 'key_memories_or_facts': 1-3 bullet facts to remember about them from this and past notes (e.g. 'Prefers email updates', 'Met during Project Phoenix migration', 'Key stakeholder for budget').

7. Status updates:
   - If the note indicates that an existing obligation was finished ('finished slides for Dave'), create a status update entry with status='completed'.

Existing graph context:
{existing_graph_str}
"""

        prompt_content = f"USER NOTE:\n{note_content}" if note_content else "Process the attached voice memo."

        contents: List[Any] = []
        if audio_bytes and audio_mime_type:
            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime_type))
        contents.append(prompt_content)

        try:
            response = self.client.models.generate_content(
                model=self.llm_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=GeminiExtractionResult,
                    temperature=0.2
                )
            )

            # Record token consumption
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                token_service.record_usage(
                    provider="gemini",
                    model=self.llm_model,
                    activity_type="ingestion",
                    prompt_tokens=getattr(response.usage_metadata, 'prompt_token_count', 0) or 0,
                    completion_tokens=getattr(response.usage_metadata, 'candidates_token_count', 0) or 0,
                    total_tokens=getattr(response.usage_metadata, 'total_token_count', 0) or 0,
                    metadata={"source": "audio" if (audio_bytes and audio_mime_type) else "text"}
                )

            if response.parsed:
                return response.parsed

            # Fallback if parsed is empty
            data = json.loads(response.text)
            return GeminiExtractionResult(**data)

        except Exception as e:
            logger.error(f"Error in Gemini extraction: {e}")
            # Fallback simple extraction
            return GeminiExtractionResult(
                summary="Captured note (fallback parse)",
                entities=[],
                relationships=[],
                status_updates=[],
                triage_reasoning=f"Parsing encountered an issue: {str(e)}"
            )

    def refine_node_with_elicitation(
        self,
        node: Dict[str, Any],
        question: str,
        user_answer: str,
        current_time_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uses Gemini to update and enrich a graph record based on the user's answer
        to an elicitation question.
        """
        # Check if OpenRouter is configured and preferred for text extraction
        # Check if OpenRouter is configured and preferred for record refinement
        if (openrouter_service.is_configured() and 
            settings.llm_provider in ("openrouter", "hybrid", "auto")):
            try:
                return openrouter_service.refine_node_with_elicitation(
                    node=node,
                    question=question,
                    user_answer=user_answer,
                    current_time_str=current_time_str
                )
            except Exception as e:
                logger.warning(f"OpenRouter record refinement failed, falling back to Gemini: {e}")

        now = current_time_str or datetime.now().astimezone().isoformat()
        prompt = f"""You are the record refinement agent of Obrigado.
CURRENT LOCAL TIME: {now} (Timezone: {settings.user_timezone})

CURRENT RECORD:
{json.dumps(node, indent=2, default=str)}

ELICITATION QUESTION ASKED:
"{question}"

USER'S RESPONSE:
"{user_answer}"

Based on the user's response, update the record fields to make it complete, actionable, and proper.
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
        try:
            res = self.client.models.generate_content(
                model=self.llm_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )

            # Record token consumption
            if hasattr(res, 'usage_metadata') and res.usage_metadata:
                token_service.record_usage(
                    provider="gemini",
                    model=self.llm_model,
                    activity_type="elicitation",
                    prompt_tokens=getattr(res.usage_metadata, 'prompt_token_count', 0) or 0,
                    completion_tokens=getattr(res.usage_metadata, 'candidates_token_count', 0) or 0,
                    total_tokens=getattr(res.usage_metadata, 'total_token_count', 0) or 0,
                    metadata={"node_id": node.get("id"), "question": question}
                )

            return json.loads(res.text)
        except Exception as e:
            logger.error(f"Error refining record with elicitation: {e}")
            return {
                "description": f"{node.get('description', '')}\nClarification: {user_answer}".strip()
            }

    def generate_daily_briefing(
        self,
        summary_type: str, # "morning", "evening", or "cto"
        current_time_str: str,
        calendar_events: List[Dict[str, Any]],
        q1_obligations: List[Dict[str, Any]],
        q2_obligations: List[Dict[str, Any]],
        waiting_on_items: List[Dict[str, Any]],
        completed_today: List[Dict[str, Any]],
        overdue_items: List[Dict[str, Any]],
        active_projects: List[Dict[str, Any]],
        people_involved: Optional[List[Dict[str, Any]]] = None,
        pending_elicitations: Optional[List[Dict[str, Any]]] = None,
        prompt_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate high-impact, actionable Morning, Evening, or CTO summary in Markdown."""
        
        now = current_time_str
        is_morning = summary_type.lower() == "morning"

        context_data = {
            "current_time": now,
            "briefing_type": summary_type,
            "calendar_events_today": calendar_events,
            "q1_critical_obligations": q1_obligations,
            "q2_strategic_obligations": q2_obligations,
            "waiting_on_dependencies": waiting_on_items,
            "completed_today": completed_today,
            "overdue_obligations": overdue_items,
            "active_projects": active_projects,
            "people_involved_today": people_involved or [],
            "pending_record_clarifications": pending_elicitations or []
        }

        context_json = json.dumps(context_data, indent=2, default=str)
        st_lower = summary_type.lower()

        full_tpl = (prompt_config.get("full_template") or "").strip() if prompt_config else ""
        if full_tpl:
            if "{context_json}" in full_tpl:
                prompt = full_tpl.replace("{context_json}", context_json)
            else:
                prompt = f"{full_tpl}\n\nCONTEXT:\n{context_json}"
        else:
            tone_override = (prompt_config.get("tone_directive") or "").strip() if prompt_config else ""
            custom_instructions = (prompt_config.get("custom_instructions") or "").strip() if prompt_config else ""
            custom_clause = f"\nUSER CUSTOM INSTRUCTIONS & CONTENT TWEAKS:\n{custom_instructions}\n" if custom_instructions else ""

            if st_lower == "morning":
                tone_clause = f"Executive Tone: {tone_override}" if tone_override else "Executive Tone: Crisp, encouraging, realistic, zero fluff."
                prompt = f"""You are the executive chief-of-staff AI for Obrigado.
Generate the START-OF-DAY (Morning Kickoff) briefing for the user.

CONTEXT:
{context_json}

GUIDELINES FOR MORNING BRIEFING:
1. {tone_clause}
2. Structure:
   - ☀️ **Today's Horizon**: Quick 1-2 sentence high-level orientation.
   - 📅 **Google Calendar Commitments**: Chronological list of today's fixed meetings & calendar events.
   - 🔥 **Top 3 Must-Win Obligations (Eisenhower Q1/Q2)**: The high-leverage things to move forward today. Note which project each belongs to.
   - 👥 **People & Stakeholders to Remember**: Highlight anyone you are meeting or following up with today, including their role, organization, and key memory facts/preferences (so the user is completely primed and never forgets who they are).
   - ⏳ **Waiting-On & Follow-ups**: Mention if someone is blocking a task and needs a quick poke today.
   - ❓ **Quick Record Clarifications**: If there are pending elicitations, ask 1 high-priority question to lock down a deadline or next step.
   - 🎯 **Suggested Day Architecture**: Propose a realistic focus block flow around calendar events.
Format in clean Markdown with emojis and bold headers. Keep it to under 350 words.
{custom_clause}
"""
            elif st_lower == "cto":
                tone_clause = f"Executive Tone: {tone_override}" if tone_override else "Executive Tone: Very brief, crisp, high-level, and strategic. Zero task-level minutiae or tactical weeds. Leadership cares about strategic momentum, workload bandwidth, and critical decisions or blockers."
                prompt = f"""You are the executive chief-of-staff AI for Obrigado.
Generate an ON-DEMAND, HIGH-LEVEL EXECUTIVE BRIEFING prepared specifically for the user's 1-on-1 update with executive leadership.

CONTEXT:
{context_json}

CRITICAL GUIDELINES FOR LEADERSHIP BRIEFING:
1. {tone_clause}
2. Mandatory Structure (use these exact bold section titles):
   - 🎯 **Executive Snapshot**: 1-2 punchy sentences summarizing overall operational posture, primary focus allocation, and runway.
   - 🏆 **Recent Wins & Deliverables**: 2-3 concise bullet points highlighting key tangible wins, shipped milestones, completed POCs, or closed loops (e.g. submitted proposals/paperwork, completed POCs, client deliverables, published content).
   - ⚡ **Current Workload & Strategic Focus**: High-level summary of active initiatives and commitment distribution (e.g. BT engagement allocation, upcoming client start dates like Principality, Tricentis Tosca POC demonstrations, upcoming presentations/rehearsals). Group by strategic umbrella.
   - ❓ **Decisions & Steer Needed from Leadership**: Specific decisions, executive sign-offs, priority arbitrations, or strategic advice needed from leadership to unblock progress. If there are no blockers or decisions currently needed from leadership, explicitly write "No critical blockers or decisions needed from leadership at this time."
3. Constraints:
   - Very brief (under 250 words total).
   - Format in clean, executive-ready Markdown with bullet points.
   - Written so the user can speak directly to leadership or paste it into a 1-on-1 doc.
{custom_clause}
"""
            else:
                tone_clause = f"Tone: {tone_override}" if tone_override else "Tone: Calming, cognitive-offloading, reassuring. Give the user peace of mind so they can disconnect."
                prompt = f"""You are the executive chief-of-staff AI for Obrigado.
Generate the END-OF-DAY (Evening Debrief & Reflection) summary for the user.

CONTEXT:
{context_json}

GUIDELINES FOR EVENING BRIEFING:
1. {tone_clause}
2. Structure:
   - 🌙 **Evening Debrief**: Brief reflection on today's progress.
   - ✅ **Wins & Progress Completed Today**: Highlight what got knocked out.
   - 🔄 **Carried-Over / Overdue Items**: Gentle, shame-free assessment. What needs rollover to tomorrow?
   - 👥 **Relationship Check-in**: 1 quick question about people interacted with today (e.g. "Did Dave send the report? Anything new to remember about him?").
   - 🌅 **Tomorrow's Runway**: The single most important priority lined up for tomorrow morning.
Format in clean Markdown with emojis and bold headers. Keep it under 300 words.
{custom_clause}
"""

        try:
            res = self.client.models.generate_content(
                model=self.llm_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3
                )
            )

            # Record token consumption
            if hasattr(res, 'usage_metadata') and res.usage_metadata:
                token_service.record_usage(
                    provider="gemini",
                    model=self.llm_model,
                    activity_type="summarisation",
                    prompt_tokens=getattr(res.usage_metadata, 'prompt_token_count', 0) or 0,
                    completion_tokens=getattr(res.usage_metadata, 'candidates_token_count', 0) or 0,
                    total_tokens=getattr(res.usage_metadata, 'total_token_count', 0) or 0,
                    metadata={"summary_type": summary_type}
                )

            return res.text or "Unable to generate briefing content."
        except Exception as e:
            logger.error(f"Error generating briefing: {e}")
            return f"### {summary_type.capitalize()} Briefing\n\n*Briefing generation failed: {e}*"

    def generate_smart_nudge_message(self, anomaly_type: str, details: Dict[str, Any]) -> Tuple[str, str]:
        """
        Generate a thoughtful title and message for a proactive graph prompt/nudge.
        Returns: (title, message)
        """
        prompt = f"""Generate a concise, proactive personal assistant prompt for the user based on their graph state.

Anomaly Type: {anomaly_type}
Details: {json.dumps(details, default=str)}

Return in JSON format:
{{
  "title": "Short punchy title (max 6 words)",
  "message": "Empathetic, actionable 1-2 sentence nudge with a clear suggested action."
}}
"""
        try:
            res = self.client.models.generate_content(
                model=self.llm_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )

            # Record token consumption
            if hasattr(res, 'usage_metadata') and res.usage_metadata:
                token_service.record_usage(
                    provider="gemini",
                    model=self.llm_model,
                    activity_type="nudge",
                    prompt_tokens=getattr(res.usage_metadata, 'prompt_token_count', 0) or 0,
                    completion_tokens=getattr(res.usage_metadata, 'candidates_token_count', 0) or 0,
                    total_tokens=getattr(res.usage_metadata, 'total_token_count', 0) or 0,
                    metadata={"anomaly_type": anomaly_type}
                )

            data = json.loads(res.text)
            return data.get("title", "Obligation Nudge"), data.get("message", "Check this item.")
        except Exception as e:
            logger.error(f"Error generating nudge message: {e}")
            return f"Attention needed: {anomaly_type}", "Please review this item in your graph."

gemini_service = GeminiService()
