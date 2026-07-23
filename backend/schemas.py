from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# --- Trackers ---
class TrackerCreate(BaseModel):
    name: str
    tracker_type: str = Field(..., description="URL, KEYWORD, ACCOUNT")
    target: str = Field(..., description="Target URL, Keyword string, or Account name")
    tier: int = Field(default=1, description="1: RSS, 2: MD, 3: Agentic")
    radar_section: str = Field(..., description="Custom section name")
    fetch_interval_minutes: int = Field(default=30)
    prompt_override: Optional[str] = None
    source_intent: str = Field(default="RSS_FEED", description="RSS_FEED, KEYWORD_DISCOVERY, ACCOUNT_TRACKING, HYBRID")
    fetch_policy: Optional[str] = None
    auth_profile_id: Optional[int] = None
    normalized_intent: Optional[str] = None

class TrackerResponse(BaseModel):
    id: int
    name: str
    tracker_type: str
    target: str
    tier: int
    radar_section: str
    is_active: bool
    fetch_interval_minutes: int
    prompt_override: Optional[str] = None
    source_intent: str
    fetch_policy: Optional[str] = None
    auth_profile_id: Optional[int] = None
    normalized_intent: Optional[str] = None
    is_high_attention: bool = False
    created_at: datetime
    last_scraped_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Intelligence & Feed ---
class IntelReportResponse(BaseModel):
    id: int
    raw_article_id: int
    source_url: str
    title: str = "Untitled"
    validity_category: str
    radar_section: str
    tracker_name: str = "Unknown"
    llm_summary: str
    importance_score: int
    created_at: datetime
    event_timestamp: Optional[str] = None
    key_entities: List[str] = []

    class Config:
        from_attributes = True

class TrendAlertSource(BaseModel):
    title: str
    url: str
    description: Optional[str] = None

class TrendAlertResponse(BaseModel):
    id: int
    entity_name: str
    alert_summary: str
    related_article_ids: List[int] = []
    created_at: datetime
    sources: List[TrendAlertSource] = []

    class Config:
        from_attributes = True

class DashboardStats(BaseModel):
    pending_count: int
    active_trackers_count: int
    active_monitors_count: int
    latest_alerts: List[TrendAlertResponse] = []

# --- Daily Briefing ---
class DailyBriefingResponse(BaseModel):
    id: int
    date_str: str
    section_name: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class DailyBriefingGenerateRequest(BaseModel):
    section_name: str = "ALL"

# --- Active Monitors (Subscriptions) ---
class SubscriptionCreate(BaseModel):
    name: str
    target_url: str
    fetch_interval_minutes: int = 60
    diff_policy: Optional[str] = None
    normalized_intent: Optional[str] = None

class SubscriptionResponse(BaseModel):
    id: int
    name: str
    target_url: str
    is_active: bool
    fetch_interval_minutes: int
    diff_policy: Optional[str] = None
    normalized_intent: Optional[str] = None
    created_at: datetime
    last_scraped_at: Optional[datetime] = None
    last_status: str

    class Config:
        from_attributes = True

class AdHocDiffTestRequest(BaseModel):
    target_url: str
    diff_policy: Optional[str] = None

class DiffTestResponse(BaseModel):
    ok: bool
    extracted_text_length: int
    sample_text: str
    ignored_nodes_count: int
    snapshot_hash: str
    error_message: Optional[str] = None

class SubscriptionUpdateResponse(BaseModel):
    id: int
    subscription_id: int
    subscription_name: str = "Unknown"
    diff_text: str
    is_read: bool
    llm_summary: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- Fact Checker (Investigation) ---
class InvestigationCreate(BaseModel):
    query: str

class InvestigationResponse(BaseModel):
    id: int
    query: str
    native_result: Optional[str] = None
    funnel_result: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class RawArticleResponse(BaseModel):
    id: int
    tracker_name: str
    title: str
    url: str
    content: str
    published_at: Optional[datetime] = None
    created_at: datetime
    # Provenance tier (docs/source_tiering.md) for dev-mode "which channel" display.
    source_tier: Optional[str] = None

    class Config:
        from_attributes = True

# --- Auth Profiles ---
class AuthProfileCreate(BaseModel):
    platform: str
    display_name: str

class AuthProfileResponse(BaseModel):
    id: int
    platform: str
    display_name: str
    storage_ref: str
    status: str
    last_checked_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- Route Testing ---
class AdHocRouteTestRequest(BaseModel):
    target: str
    source_intent: str
    fetch_policy: Optional[str] = None
    auth_profile_id: Optional[int] = None

class RouteInfo(BaseModel):
    route_id: str
    adapter: str
    url_or_command: str
    purpose: str
    requires_auth: bool
    auth_profile_id: Optional[int] = None
    auth_status: str = "none"
    http_status: int
    ok: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    item_count: int
    latest_item_time: Optional[datetime] = None
    sample_titles: List[str]
    quality_score: float
    fallback_triggered: bool

class RouteTestResponse(BaseModel):
    original_target: str
    resolved_routes: List[RouteInfo]
    selected_route: Optional[str] = None
    fallback_triggered: bool
    item_count: int
    latest_item_time: Optional[datetime] = None
    sample_titles: List[str]
    quality_score: float
    error_type: Optional[str] = None
    error_message: Optional[str] = None

# --- Ingestion Tracing ---
class PipelineEventResponse(BaseModel):
    id: int
    run_id: int
    step_index: int
    created_at: datetime
    stage: str
    route_id: Optional[str] = None
    adapter: Optional[str] = None
    input_data: Optional[str] = None
    output_summary: Optional[str] = None
    status: str
    duration_ms: int
    error: Optional[str] = None

    class Config:
        from_attributes = True

class PipelineRunResponse(BaseModel):
    id: int
    tracker_id: Optional[int] = None
    subscription_id: Optional[int] = None
    status: str
    normalized_intent: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    total_routes: int
    total_items: int
    accepted_items: int
    error_summary: Optional[str] = None
    cost_flag_browser: bool
    cost_flag_llm: bool
    events: List[PipelineEventResponse] = []

    class Config:
        from_attributes = True
