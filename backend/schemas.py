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
    cookie_string: Optional[str] = None

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

class SubscriptionResponse(BaseModel):
    id: int
    name: str
    target_url: str
    is_active: bool
    fetch_interval_minutes: int
    created_at: datetime
    last_scraped_at: Optional[datetime] = None
    last_status: str

    class Config:
        from_attributes = True

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
