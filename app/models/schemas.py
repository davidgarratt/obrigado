from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

NodeType = Literal["obligation", "project", "person", "organization", "event", "context", "reference"]
CategoryType = Literal["work", "personal", "health", "admin", "social"]
StatusType = Literal["pending", "in_progress", "blocked", "waiting_on", "completed", "deferred", "cancelled"]
PriorityType = Literal["critical", "high", "medium", "low"]
RelationType = Literal["PART_OF", "DEPENDS_ON", "BLOCKS", "WAITING_ON", "ASSIGNED_TO", "INVOLVES", "SCHEDULED_FOR", "RELATES_TO"]
EisenhowerQuadrant = Literal["Q1_DO_FIRST", "Q2_SCHEDULE", "Q3_DELEGATE", "Q4_DONT_DO"]

# --- Gemini Structured Extraction Models ---

class GeminiExtractedEntity(BaseModel):
    title: str = Field(description="Clear, concise title of the entity (e.g. 'Draft Q3 Budget', 'Mum', 'Project Alpha')")
    node_type: NodeType = Field(description="Type of entity: obligation (action item), project, person, organization, event (timed appointment), context, reference")
    category: CategoryType = Field(default="work", description="Life sphere: work, personal, health, admin, social")
    description: Optional[str] = Field(default="", description="Key context, details, requirements")
    status: StatusType = Field(default="pending", description="Current status")
    priority: PriorityType = Field(default="medium", description="Priority level: critical, high, medium, low")
    urgency_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Urgency from 0.0 (distant/none) to 1.0 (immediate)")
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance from 0.0 (trivial) to 1.0 (vital impact)")
    due_date: Optional[str] = Field(default=None, description="ISO format date or datetime string (e.g. 2026-10-28 or 2026-10-28T15:00:00)")
    is_calendar_candidate: bool = Field(default=False, description="True if this is a timed event, doctor/dentist appointment, flight, or hard scheduled meeting")
    calendar_start: Optional[str] = Field(default=None, description="ISO datetime string for calendar start time")
    calendar_end: Optional[str] = Field(default=None, description="ISO datetime string for calendar end time")
    estimated_minutes: Optional[int] = Field(default=30, description="Estimated duration in minutes")
    energy_required: Optional[Literal["low", "medium", "high"]] = Field(default="medium", description="Energy needed: low (routine), medium, high (deep work)")
    clarification_needed: Optional[str] = Field(default=None, description="If details are ambiguous, proactive question to ask the user")

class GeminiExtractedRelationship(BaseModel):
    source_title: str = Field(description="Title of source entity (must match one in entities or existing graph)")
    target_title: str = Field(description="Title of target entity")
    relation_type: RelationType = Field(description="Relation: PART_OF, DEPENDS_ON, BLOCKS, WAITING_ON, ASSIGNED_TO, INVOLVES, SCHEDULED_FOR, RELATES_TO")
    context_notes: Optional[str] = Field(default=None, description="Why this relation exists")

class GeminiStatusUpdate(BaseModel):
    target_title: str = Field(description="Title of the existing entity being updated")
    new_status: StatusType = Field(description="New status, e.g. completed, in_progress, blocked")
    notes: Optional[str] = Field(default="", description="Update notes")

class GeminiElicitationItem(BaseModel):
    target_title: str = Field(description="Title of entity that needs clarification or more details to form a complete record")
    question: str = Field(description="Targeted, conversational elicitation question (e.g. 'By when does this report need to be finalized?', 'Who is Marcus and what is his role/relationship to you?')")
    field_target: str = Field(description="Target field: deadline, person_identity, definition_of_done, project_affiliation, next_action")
    suggested_options: List[str] = Field(default_factory=list, description="2 to 4 quick, 1-click selectable options for the user to pick from")

class GeminiPersonProfile(BaseModel):
    name: str = Field(description="Full name or alias of the person")
    role_or_title: Optional[str] = Field(default="", description="Role or professional title (e.g. VP Engineering, Tax Accountant, Mom, Cardiologist)")
    organization: Optional[str] = Field(default="", description="Company or group (e.g. Acme Corp, NHS, Family)")
    relationship_type: Optional[str] = Field(default="colleague", description="Relationship sphere: colleague, manager, direct_report, client, family, friend, vendor")
    key_memories_or_facts: List[str] = Field(default_factory=list, description="Key personal or professional memory notes to help the user remember who they are, their preferences, or history")

class GeminiExtractionResult(BaseModel):
    summary: str = Field(description="One-sentence synopsis of what was understood and triaged from the note")
    entities: List[GeminiExtractedEntity] = Field(default_factory=list, description="Extracted nodes")
    relationships: List[GeminiExtractedRelationship] = Field(default_factory=list, description="Extracted edges")
    status_updates: List[GeminiStatusUpdate] = Field(default_factory=list, description="Updates to existing obligations or projects")
    elicitations: List[GeminiElicitationItem] = Field(default_factory=list, description="Proactive elicitation questions to gain missing information needed for proper records")
    person_profiles: List[GeminiPersonProfile] = Field(default_factory=list, description="Rich memory profiles for any people mentioned in the note")
    triage_reasoning: str = Field(description="Brief rationale of decisions made regarding urgency, importance, and calendar scheduling")

# --- API Models ---

class NoteCaptureRequest(BaseModel):
    content: str
    source_type: Literal["text", "audio", "webhook", "api"] = "text"
    auto_sync_calendar: bool = True

class WorkloadRiskAssessment(BaseModel):
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    risk_flagged: bool = False
    stress_score: int = 0
    total_active_obligations: int = 0
    q1_urgent_count: int = 0
    colliding_deadlines_count: int = 0
    overdue_count: int = 0
    estimated_focus_hours: float = 0.0
    summary: str = ""
    details: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)
    conflicting_obligations: List[Dict[str, Any]] = Field(default_factory=list)

class NoteCaptureResponse(BaseModel):
    note_id: str
    summary: str
    triage_reasoning: str
    created_entities: List[Dict[str, Any]]
    created_relationships: List[Dict[str, Any]]
    calendar_actions: List[Dict[str, Any]]
    prompts_generated: List[Dict[str, Any]]
    elicitations: List[Dict[str, Any]] = Field(default_factory=list)
    people_profiles: List[Dict[str, Any]] = Field(default_factory=list)
    workload_risk: Optional[WorkloadRiskAssessment] = None

class ElicitationAnswerRequest(BaseModel):
    elicitation_id: str
    user_answer: str

class AddPersonMemoryRequest(BaseModel):
    memory_fact: str
    category: str = "general"

class UpdatePersonProfileRequest(BaseModel):
    role_or_title: Optional[str] = None
    organization: Optional[str] = None
    relationship_type: Optional[str] = None
    notes: Optional[str] = None

class NodeCreate(BaseModel):
    title: str
    node_type: NodeType
    category: CategoryType = "work"
    status: StatusType = "pending"
    priority: PriorityType = "medium"
    urgency_score: float = 0.5
    importance_score: float = 0.5
    due_date: Optional[str] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    energy_required: Literal["low", "medium", "high"] = "medium"
    estimated_minutes: int = 30
    description: Optional[str] = ""
    metadata: Optional[Dict[str, Any]] = None

class NodeUpdate(BaseModel):
    title: Optional[str] = None
    node_type: Optional[NodeType] = None
    category: Optional[CategoryType] = None
    status: Optional[StatusType] = None
    priority: Optional[PriorityType] = None
    urgency_score: Optional[float] = None
    importance_score: Optional[float] = None
    due_date: Optional[str] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    calendar_sync_status: Optional[str] = None
    energy_required: Optional[Literal["low", "medium", "high"]] = None
    estimated_minutes: Optional[int] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class NodeResponse(BaseModel):
    id: str
    title: str
    node_type: str
    category: str
    status: str
    priority: str
    urgency_score: float
    importance_score: float
    eisenhower_quadrant: str
    due_date: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    calendar_event_id: Optional[str]
    calendar_sync_status: str
    energy_required: str
    estimated_minutes: int
    description: Optional[str]
    metadata_json: str
    created_at: str
    updated_at: str
    completed_at: Optional[str]

class EdgeCreate(BaseModel):
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None

class EdgeResponse(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    weight: float
    metadata_json: str
    created_at: str

class GraphDataResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    stats: Dict[str, Any]

class DailySummaryResponse(BaseModel):
    id: str
    summary_date: str
    summary_type: Literal["morning", "evening"]
    content_markdown: str
    metrics: Dict[str, Any]
    created_at: str

class PromptItem(BaseModel):
    id: str
    prompt_type: str
    title: str
    message: str
    target_node_id: Optional[str]
    status: str
    action_data: Dict[str, Any]
    created_at: str
