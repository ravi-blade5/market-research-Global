from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchMode(str, Enum):
    quick = "quick"
    deep = "deep"


class FreshnessWindow(str, Enum):
    six_months = "6m"
    twelve_months = "12m"


class RunStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    researching = "researching"
    verifying = "verifying"
    exporting = "exporting"
    completed = "completed"
    failed = "failed"


class AgentStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SourceCredibility(str, Enum):
    official_filing = "official_filing"
    investor_relations = "investor_relations"
    earnings_transcript = "earnings_transcript"
    regulator = "regulator"
    company_page = "company_page"
    reputable_news = "reputable_news"
    job_or_career_page = "job_or_career_page"
    public_profile = "public_profile"
    partner_page = "partner_page"
    system = "system"
    rejected = "rejected"


class SourceTier(str, Enum):
    tier_1_official_financial = "tier_1_official_financial"
    tier_2_official_company = "tier_2_official_company"
    tier_3_reputable_context = "tier_3_reputable_context"
    tier_4_directional_signal = "tier_4_directional_signal"
    system = "system"
    rejected = "rejected"


class EvidenceSignalType(str, Enum):
    financial_metric = "financial_metric"
    investment = "investment"
    partnership_deal = "partnership_deal"
    strategic_priority = "strategic_priority"
    technology_stack = "technology_stack"
    hiring_footprint = "hiring_footprint"
    it_investment = "it_investment"
    news_signal = "news_signal"
    vendor_outsourcing = "vendor_outsourcing"
    executive_buying_center = "executive_buying_center"
    department_people_signal = "department_people_signal"
    ai_strategy = "ai_strategy"
    hcltech_opportunity = "hcltech_opportunity"
    consensus_move = "consensus_move"
    evidence_quality = "evidence_quality"


class ResearchRunCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    mode: ResearchMode = ResearchMode.deep
    freshness_window: FreshnessWindow = FreshnessWindow.twelve_months
    department: str | None = Field(default=None, max_length=120)


class AgentRun(BaseModel):
    name: str
    model: str | None = None
    reasoning_effort: str | None = None
    tools: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    message: str | None = None


class ProviderRun(BaseModel):
    provider: str
    operation: str
    status: AgentStatus
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSource(BaseModel):
    id: str = Field(default_factory=lambda: f"src_{uuid4().hex[:12]}")
    url: str
    title: str
    publisher: str | None = None
    published_at: str | None = None
    accessed_at: datetime = Field(default_factory=utc_now)
    credibility: SourceCredibility
    credibility_score: float = Field(ge=0, le=1)
    source_tier: SourceTier | None = None
    allowed_uses: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None


class SourceSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: f"snap_{uuid4().hex[:12]}")
    source_id: str
    captured_at: datetime = Field(default_factory=utc_now)
    text_excerpt: str | None = None
    storage_uri: str | None = None
    checksum: str | None = None


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: f"claim_{uuid4().hex[:12]}")
    text: str
    section_id: str
    claim_type: Literal["fact", "inference", "recommendation", "unavailable"]
    evidence_source_ids: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0, ge=0, le=1)
    verification_status: Literal["pending", "verified", "rejected", "unavailable"] = "pending"


class ExtractedValue(BaseModel):
    id: str = Field(default_factory=lambda: f"val_{uuid4().hex[:12]}")
    label: str
    value: str | float | int | None
    unit: str | None = None
    period: str | None = None
    source_id: str | None = None
    exact: bool = True
    unavailable_reason: str | None = None


class EvidenceSignal(BaseModel):
    id: str = Field(default_factory=lambda: f"sig_{uuid4().hex[:12]}")
    section_id: str
    signal_type: EvidenceSignalType
    title: str
    detail: str
    signal_strength: Literal["exact", "directional", "inferred", "unsupported"]
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0, ge=0, le=1)
    detected_at: datetime = Field(default_factory=utc_now)


class EvidenceTableRow(BaseModel):
    id: str = Field(default_factory=lambda: f"row_{uuid4().hex[:12]}")
    table_name: str
    row_type: Literal["source", "snapshot", "claim", "signal", "extracted_value", "section_summary", "quality_check"]
    section_id: str | None = None
    title: str
    detail: str
    normalized_fields: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    snapshot_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    extracted_value_ids: list[str] = Field(default_factory=list)
    source_tier: SourceTier | None = None
    signal_type: EvidenceSignalType | None = None
    confidence_score: float = Field(default=0, ge=0, le=1)
    include_in_analysis: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class RejectedClaim(BaseModel):
    claim_text: str
    reason: str
    rejected_at: datetime = Field(default_factory=utc_now)


class QualityCheck(BaseModel):
    name: str
    passed: bool
    message: str
    checked_at: datetime = Field(default_factory=utc_now)
    severity: Literal["info", "warning", "blocker"] = "info"


class ReportSection(BaseModel):
    id: str
    title: str
    summary: str
    content: dict[str, Any] = Field(default_factory=dict)
    claim_ids: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0, ge=0, le=1)
    status: Literal["complete", "partial", "unavailable"] = "partial"


class ResearchObjective(BaseModel):
    tag: Literal["RESEARCH", "DELIVERABLE", "VERIFY", "STRATEGY"]
    text: str
    section_id: str | None = None


class ResearchAnchor(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    snapshot_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    extracted_value_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    table_row_ids: list[str] = Field(default_factory=list)
    raw_urls: list[str] = Field(default_factory=list)


class SlideSpec(BaseModel):
    id: str
    title: str
    layout: Literal["cover", "section", "table", "strategy", "evidence"]
    bullets: list[str] = Field(default_factory=list)
    chart: dict[str, Any] | None = None
    speaker_notes: list[str] = Field(default_factory=list)
    citation_source_ids: list[str] = Field(default_factory=list)


class DeckSpec(BaseModel):
    title: str
    subtitle: str
    brand_tokens: dict[str, str]
    slides: list[SlideSpec]


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex[:12]}")
    kind: Literal["pptx", "pdf", "evidence_json"]
    path: str
    created_at: datetime = Field(default_factory=utc_now)
    quality_checks: list[QualityCheck] = Field(default_factory=list)


class AccountReport(BaseModel):
    run_id: str
    company_name: str
    department: str | None = None
    generated_at: datetime = Field(default_factory=utc_now)
    mode: ResearchMode
    freshness_window: FreshnessWindow
    sections: list[ReportSection]
    claims: list[Claim]
    sources: list[EvidenceSource]
    snapshots: list[SourceSnapshot] = Field(default_factory=list)
    extracted_values: list[ExtractedValue] = Field(default_factory=list)
    evidence_signals: list[EvidenceSignal] = Field(default_factory=list)
    evidence_table_rows: list[EvidenceTableRow] = Field(default_factory=list)
    rejected_claims: list[RejectedClaim] = Field(default_factory=list)
    quality_checks: list[QualityCheck] = Field(default_factory=list)
    research_anchor: ResearchAnchor = Field(default_factory=ResearchAnchor)
    deck_spec: DeckSpec | None = None
    artifacts: list[Artifact] = Field(default_factory=list)


class ResearchRun(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:12]}")
    company_name: str
    department: str | None = None
    mode: ResearchMode
    freshness_window: FreshnessWindow
    status: RunStatus = RunStatus.queued
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    progress: int = Field(default=0, ge=0, le=100)
    expected_duration_seconds: int | None = None
    workflow_profile: str = "quick_scan"
    run_notes: list[str] = Field(default_factory=list)
    agents: list[AgentRun] = Field(default_factory=list)
    provider_runs: list[ProviderRun] = Field(default_factory=list)
    report: AccountReport | None = None
    error: str | None = None


class DrilldownRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    max_evidence_rows: int = Field(default=24, ge=1, le=80)


class DrilldownRun(BaseModel):
    id: str = Field(default_factory=lambda: f"drill_{uuid4().hex[:12]}")
    parent_run_id: str
    question: str
    answer: str
    source_ids: list[str] = Field(default_factory=list)
    evidence_rows: list[dict[str, Any]] = Field(default_factory=list)
    analytics: dict[str, Any] = Field(default_factory=dict)
    retrieval_mode: str = "duckdb_keyword_sql"
    model: str | None = None
    provider: str = "deterministic"
    created_at: datetime = Field(default_factory=utc_now)
