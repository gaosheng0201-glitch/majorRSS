from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime, timezone
from sqlalchemy import Column, Text

def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class AuthProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str
    display_name: str
    storage_ref: str
    status: str = Field(default="Active")
    last_checked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now_naive)

class Tracker(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    tracker_type: str = Field(description="URL, KEYWORD, ACCOUNT")
    target: str = Field(description="Target URL, Keyword string, or Account name")
    tier: int = Field(default=1, description="Fallback tier for direct URLs (1: RSS, 2: MD, 3: Agentic)")
    radar_section: str = Field(description="Custom section name (e.g. Frontier Outpost, Geek Radar, etc.)")
    is_active: bool = Field(default=True)
    fetch_interval_minutes: int = Field(default=30)
    prompt_override: Optional[str] = Field(default=None, description="Custom instructions for LLM extraction")
    cookie_string: Optional[str] = Field(default=None, description="[DEPRECATED] Optional cookie string. Use AuthProfile instead.")
    source_intent: str = Field(default="RSS_FEED", description="RSS_FEED, KEYWORD_DISCOVERY, ACCOUNT_TRACKING, HYBRID")
    fetch_policy: Optional[str] = Field(default=None, description="JSON policy overrides")
    auth_profile_id: Optional[int] = Field(default=None, foreign_key="authprofile.id", description="Auth Profile reference")
    normalized_intent: Optional[str] = Field(default=None, description="JSON string caching intent definition mapping")
    # High-attention targets alert earlier (愿景 #2): a CONFIRMED/CORROBORATED
    # increment here is pushed, not just shown in the quiet dashboard.
    is_high_attention: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now_naive)
    last_scraped_at: Optional[datetime] = None

class RawArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tracker_id: int = Field(foreign_key="tracker.id")
    title: str
    url: str = Field(unique=True, index=True)
    content: str = Field(description="Raw text or HTML extracted from the page")
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now_naive)
    processed: bool = Field(default=False, description="Whether it has been processed by LLM")
    # R3 semantic layer: which story thread this item was clustered into
    # (first_seen for radar/increment logic is created_at; published_at is the
    # source's own date used by the age gate).
    thread_id: Optional[int] = Field(default=None, foreign_key="storythread.id", nullable=True, index=True)
    # Relevance gate: below-threshold items stay visible in the Raw Feed but are
    # excluded from LLM fusion (token economy). Only set when a REAL embedder is
    # configured — the fallback bag-of-words must never silently drop content.
    relevance_gated: bool = Field(default=False, index=True)
    # Provenance tier stamped at intake (docs/source_tiering.md): primary /
    # curated / aggregated. Read by the fusion gate (P1.1), scoring, feedback and
    # dev-mode display. Nullable: legacy rows are unknown → treated as aggregated
    # (must earn a summary) by the gate.
    source_tier: Optional[str] = Field(default=None, index=True)
    # Cross-target visibility (author ruling 2026-08-26: a piece concerning
    # several targets shows under ALL of them — the same piece, not copies).
    # JSON list of OTHER tracker ids whose planned profile this item matches,
    # computed deterministically at intake (services/attribution.py). Ownership
    # (tracker_id) stays with the fetcher; this only widens the filter.
    also_tracker_ids: Optional[str] = Field(default=None)
    # True when this item arrived through a route the user created by NAMING an
    # account (the people radar) — stamped at intake, like source_tier, per
    # docs/source_tiering.md §2 "capture now, weight-application later".
    # The fusion gate used to re-derive this at consumption time from the item's
    # URL host, which is not the same question: a topic feed linking to x.com
    # would earn the people-radar bypass, while an account read through a host
    # not on the list would lose it. Only the resolver knows, so only the
    # resolver decides. Legacy rows are False → they simply take the normal path.
    from_account: bool = Field(default=False, index=True)

class IntelReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    raw_article_id: int = Field(foreign_key="rawarticle.id", unique=True)
    source_url: str
    validity_category: str = Field(description="[SPAM], [MALICIOUS_LINK], [VALID_NEWS]")
    radar_section: str = Field(description="Inherited from Tracker section")
    llm_summary: str
    importance_score: int = Field(default=0, description="1 to 5")
    original_content_hash: str = Field(description="Hash for anti-poisoning signature")
    created_at: datetime = Field(default_factory=utc_now_naive)
    shared: bool = Field(default=False, description="Whether it has been pushed to the central server")
    key_entities: str = Field(default="[]", description="JSON list of extracted entities")
    event_timestamp: Optional[str] = Field(default=None, description="ISO8601 string of the actual event/publish time extracted by LLM")

class TrendAlert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_name: str = Field(index=True)
    alert_summary: str
    related_article_ids: str = Field(description="Comma separated StoryThread IDs (P2.1; was IntelReport IDs pre-P2.1)")
    created_at: datetime = Field(default_factory=utc_now_naive)

class PipelineStatus(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tracker_name: str = Field(description="Name of the tracker being processed")
    action_type: str = Field(description="e.g., 'Scraping', 'AI Processing'")
    detail: str = Field(description="Details of the current operation")
    updated_at: datetime = Field(default_factory=utc_now_naive)

class DailyBriefing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date_str: str = Field(index=True, description="YYYY-MM-DD")
    section_name: str = Field(default="ALL", description="Target section, or ALL for comprehensive")
    content: str = Field(description="Synthesized briefing generated by Gemini")
    created_at: datetime = Field(default_factory=utc_now_naive)

class TokenUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    model_name: str
    action_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    created_at: datetime = Field(default_factory=utc_now_naive)

class Subscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    target_url: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)
    fetch_interval_minutes: int = Field(default=60)
    diff_policy: Optional[str] = Field(default=None, description="JSON policy overrides for page diff")
    normalized_intent: Optional[str] = Field(default=None, description="JSON string caching intent definition mapping")
    created_at: datetime = Field(default_factory=utc_now_naive)
    last_scraped_at: Optional[datetime] = None
    last_status: str = Field(default="Idle")

class PageSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subscription_id: int = Field(foreign_key="subscription.id")
    content_hash: str
    content_text: str
    created_at: datetime = Field(default_factory=utc_now_naive)

class SubscriptionUpdate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subscription_id: int = Field(foreign_key="subscription.id")
    diff_text: str
    is_read: bool = Field(default=False)
    llm_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now_naive)

class SourcePreset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    preset_id: str = Field(unique=True, index=True)
    title: str
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    source_type: str = Field(index=True)
    url: str = Field(sa_column=Column(Text))
    canonical_site: Optional[str] = Field(default=None, sa_column=Column(Text))
    categories_json: str = Field(default="[]", sa_column=Column(Text))
    tags_json: str = Field(default="[]", sa_column=Column(Text))
    language: Optional[str] = Field(default=None, index=True)
    region: Optional[str] = Field(default=None, index=True)
    importance: Optional[str] = Field(default=None, index=True)
    noise_level: Optional[str] = Field(default=None)
    update_frequency: Optional[str] = Field(default=None)
    requires_auth: bool = Field(default=False)
    owner_type: str = Field(default="built_in", index=True)
    verification_status: str = Field(default="candidate", index=True)
    raw_metadata: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now_naive)
    updated_at: datetime = Field(default_factory=utc_now_naive)

class SourcePresetCollection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: str = Field(unique=True, index=True)
    title: str
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    categories_json: str = Field(default="[]", sa_column=Column(Text))
    owner_type: str = Field(default="built_in", index=True)
    default_keywords_json: str = Field(default="[]", sa_column=Column(Text))
    default_summary_style: Optional[str] = None
    source_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now_naive)
    updated_at: datetime = Field(default_factory=utc_now_naive)

class SourcePresetCollectionItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: str = Field(index=True)
    preset_id: str = Field(index=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now_naive)

class InvestigationRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    query: str
    native_result: Optional[str] = None
    funnel_result: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now_naive)

class SchemaVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: str = Field(unique=True, index=True)
    applied_at: datetime = Field(default_factory=utc_now_naive)

class TaskRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_type: str = Field(description="e.g. SCRAPE, PROCESS, TREND_SCAN, BRIEFING")
    target_type: Optional[str] = Field(default=None, description="e.g. TRACKER, SECTION")
    target_id: Optional[str] = Field(default=None, description="Tracker ID, or Section Name, or null")
    payload: Optional[str] = Field(default=None, description="JSON string of additional arguments")
    status: str = Field(default="PENDING", description="PENDING, RUNNING, COMPLETED, FAILED")
    retry_count: int = Field(default=0, description="Number of times this task was retried")
    max_retries: int = Field(default=3, description="Maximum retry limit")
    created_at: datetime = Field(default_factory=utc_now_naive)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None

class PipelineRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tracker_id: Optional[int] = Field(default=None, foreign_key="tracker.id", nullable=True)
    subscription_id: Optional[int] = Field(default=None, foreign_key="subscription.id", nullable=True)
    status: str = Field(default="RUNNING") # RUNNING, SUCCESS, NO_NEW_ITEMS, FAILED
    normalized_intent: Optional[str] = Field(default=None, description="JSON representing normalized intent mapping snapshot")
    started_at: datetime = Field(default_factory=utc_now_naive)
    finished_at: Optional[datetime] = None
    total_routes: int = Field(default=0)
    total_items: int = Field(default=0)
    accepted_items: int = Field(default=0)
    error_summary: Optional[str] = None
    cost_flag_browser: bool = Field(default=False)
    cost_flag_llm: bool = Field(default=False)

class PipelineEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="pipelinerun.id")
    step_index: int = Field(description="Sequence step number (1-indexed)")
    created_at: datetime = Field(default_factory=utc_now_naive)
    stage: str = Field(description="RESOLVE, FETCH, DEDUPLICATE, LLM_FILTER, SAVE")
    route_id: Optional[str] = None
    adapter: Optional[str] = None
    input_data: Optional[str] = None # Masked/desensitized target snippet
    output_summary: Optional[str] = None # Text snippet/length/hash summary (max 100 chars)
    status: str = Field(default="SUCCESS") # SUCCESS, FAILED
    duration_ms: int = Field(default=0)
    error: Optional[str] = None

# --- R1 fetch runtime (2026-07-05) ---

class HttpCacheEntry(SQLModel, table=True):
    """Conditional-GET validators per URL, persisted across restarts so a
    5-minute poll of an unchanged changelog page costs one 304 (愿景 #4)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(unique=True, index=True)
    etag: Optional[str] = None
    last_modified: Optional[str] = None  # raw HTTP header value
    content_hash: Optional[str] = None   # sha256 of body, for servers lacking validators
    last_status: Optional[int] = None
    last_checked_at: datetime = Field(default_factory=utc_now_naive)
    updated_at: datetime = Field(default_factory=utc_now_naive)

class SourceHealth(SQLModel, table=True):
    """Per-domain (or per-route-key) reliability record driving backoff and
    'quarantine an unstable source' decisions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)  # domain or route key
    state: str = Field(default="healthy")      # healthy | degraded | failed | quarantined
    consecutive_failures: int = Field(default=0)
    total_success: int = Field(default=0)
    total_failure: int = Field(default=0)
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error_type: Optional[str] = None
    next_eligible_at: Optional[datetime] = None  # backoff gate; skip source until then
    avg_latency_ms: int = Field(default=0)
    updated_at: datetime = Field(default_factory=utc_now_naive)

class ArticleEmbedding(SQLModel, table=True):
    """Embedding vector per RawArticle, kept in its own table so RawArticle
    stays lean and items can be re-embedded (e.g. after a model change) without
    touching the article row. Vector stored as JSON text — engine-agnostic;
    pgvector/sqlite-vec are optional accelerations layered on later."""
    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="rawarticle.id", unique=True, index=True)
    model_name: str = Field(description="Embedder that produced this vector")
    dim: int = Field(default=0)
    vector: str = Field(sa_column=Column(Text), description="JSON list[float]")
    relevance: Optional[float] = Field(default=None, description="Max cosine vs the tracker's topic profile")
    created_at: datetime = Field(default_factory=utc_now_naive)

class StoryThread(SQLModel, table=True):
    """A clustered event/issue line for a target. New content is compared to
    thread centroids: same event → merge (silent), new event → new thread.
    Carries the state the radar reasons over (愿景 增量优先 + 线索生命周期)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tracker_id: Optional[int] = Field(default=None, foreign_key="tracker.id", nullable=True, index=True)
    # 全局线索 (author ruling 2026-09-01): a thread is ONE event across every
    # target; `tracker_id` is only the target that started it (kept for
    # narration/section/alerts). This JSON list is the LENS — every target the
    # thread concerns, unioned from members' owner + cross-target visibility
    # stamps as they join. The radar's filter chips test membership here.
    tracker_ids: Optional[str] = Field(default=None)
    title: Optional[str] = None
    centroid: Optional[str] = Field(default=None, sa_column=Column(Text), description="JSON list[float] running centroid")
    member_count: int = Field(default=0)
    distinct_source_count: int = Field(default=0)   # for resonance / corroboration
    # Lifecycle: LEAD (single unverified source) → CORROBORATED (N sources) →
    # CONFIRMED (a first-party source present). Speed of promotion = resonance.
    lifecycle: str = Field(default="LEAD")
    importance_score: int = Field(default=0)
    resonance_score: float = Field(default=0.0, description="distinct sources / hour since first_seen")
    is_resonant: bool = Field(default=False, description="crossed the resonance threshold (愿景 #2 alert signal)")
    first_seen_at: datetime = Field(default_factory=utc_now_naive)
    last_update_at: datetime = Field(default_factory=utc_now_naive)
    # --- P2.1: the fused event summary lives on the thread (single source of
    # truth; IntelReport deprecated). Written by process_tracker_fusion when the
    # thread's members are worth summarizing — one summary per event, not per
    # blind batch. Feed / briefing / trends / stats all read these. ---
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    validity_category: Optional[str] = Field(default=None, description="[VALID_NEWS]/[NOISE]/... classified at fusion")
    radar_section: Optional[str] = Field(default=None, description="denormalized from tracker for section filters")
    key_entities: str = Field(default="[]", description="JSON list of extracted entities")
    event_timestamp: Optional[str] = Field(default=None, description="ISO8601 of the underlying event")
    source_url: Optional[str] = Field(default=None, description="'Fused from N sources (...)' descriptor for display")
    summarized_at: Optional[datetime] = Field(default=None, index=True, description="when summary last (re)generated — feed ordering + incremental re-synth guard")
    # P1.1 gate marker: when the gate last evaluated this thread. A gated thread
    # is re-checked only when it changes (last_update_at > gate_checked_at), not
    # every cycle — kills the per-cycle churn over the whole gated backlog.
    gate_checked_at: Optional[datetime] = Field(default=None)
    # Snapshot of the signals AT the last fusion, so re-fusion can tell a real
    # development (new independent publishers / lifecycle promotion) from more
    # copies of the same story. Without it every trickle of follow-ups re-burned
    # the summary and bumped the thread back to the top of the feed.
    fused_source_count: Optional[int] = Field(default=None)
    fused_lifecycle: Optional[str] = Field(default=None)

class RadarAlert(SQLModel, table=True):
    """A thread-level alert. Default is a quiet dashboard; an alert is created
    only when an increment earns interruption (愿景 #2). Every alert stores its
    trigger reason so the UI can always answer 'why am I being interrupted?'."""
    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: int = Field(foreign_key="storythread.id", index=True)
    tracker_id: Optional[int] = Field(default=None, foreign_key="tracker.id", nullable=True)
    reason: str = Field(index=True, description="RESONANCE | CONFIRMED_HIGH_ATTENTION | CORROBORATED_HIGH_ATTENTION")
    title: Optional[str] = None
    summary: Optional[str] = Field(default=None, sa_column=Column(Text), description="Synthesized increment with citations (if a model is configured)")
    distinct_source_count: int = Field(default=0)
    lifecycle: Optional[str] = None
    delivered: bool = Field(default=False, description="Pushed as a system notification")
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now_naive)

class AccountGuardState(SQLModel, table=True):
    """Per auth-account rate/risk state (愿景 #10 防封 + 平衡). Budget is an
    AIMD-calibrated safe allowance, not a fear ceiling; circuit trips on risk
    signals and recovers half-open."""
    id: Optional[int] = Field(default=None, primary_key=True)
    account_key: str = Field(unique=True, index=True)  # e.g. "twitter:profile_7"
    hourly_budget: int = Field(default=20)             # current AIMD allowance
    window_started_at: datetime = Field(default_factory=utc_now_naive)
    window_count: int = Field(default=0)               # requests spent in current hour window
    circuit_state: str = Field(default="closed")       # closed | open | half_open
    circuit_until: Optional[datetime] = None           # cooldown end when open
    consecutive_clean_days: int = Field(default=0)
    last_budget_calibrated_at: Optional[datetime] = None  # anchor for AIMD additive increase
    last_risk_signal_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    total_authorized_yield: int = Field(default=0)      # items produced via this account (utilization sentinel)
    last_yield_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now_naive)
