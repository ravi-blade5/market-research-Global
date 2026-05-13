from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from app.agents.base import Agent, AgentContext
from app.brand import css_tokens
from app.models import (
    AccountReport,
    Claim,
    DeckSpec,
    EvidenceSignal,
    EvidenceSignalType,
    EvidenceTableRow,
    EvidenceSource,
    ExtractedValue,
    FreshnessWindow,
    QualityCheck,
    ReportSection,
    ResearchObjective,
    ResearchRun,
    ResearchMode,
    SlideSpec,
    SourceCredibility,
    SourceSnapshot,
    SourceTier,
)
from app.providers.base import SynthesisResult


REPORT_SECTION_ORDER = [
    ("company_overview", "Company Overview and Financial Snapshot"),
    ("financial_trends", "Revenue, R&D, Geography, and Segment Trends"),
    ("recent_investments", "Recent Investments and Capital Allocation"),
    ("partnerships_deals", "Partnerships, Deals, and Commercial Moves"),
    ("account_priorities", "Account Priorities by Business Function"),
    ("it_spend", "IT Spend and Investment Signals"),
    ("technology_stack", "Technology Stack Analysis"),
    ("footprint_hiring", "Global Footprint and Hiring Analysis"),
    ("key_signals", "Key Signals"),
    ("outsourcing_vendor", "Outsourcing and Vendor Analysis"),
    ("executives", "Key Executives and Buying-Center Map"),
    ("ai_strategy", "AI Strategy Assessment"),
    ("hcltech_penetration", "HCLTech Account Penetration Strategy"),
    ("consensus", "Consensus Recommendation"),
    ("evidence_appendix", "Sources and Evidence Appendix"),
]


SOURCE_TOKEN_RE = re.compile(r"src_[0-9a-f]{8,16}")
YEAR_RE = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
ISO_DATE_RE = re.compile(r"(?<!\d)(20[0-3]\d)[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])(?!\d)")
URL_YEAR_MONTH_RE = re.compile(r"/(20[0-3]\d)/(0?[1-9]|1[0-2])(?:/|$)")
MONTH_DATE_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+([0-3]?\d),?\s+(20[0-3]\d)\b",
    re.IGNORECASE,
)

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

RECENCY_SENSITIVE_SECTIONS = {
    "recent_investments",
    "partnerships_deals",
    "account_priorities",
    "it_spend",
    "key_signals",
    "outsourcing_vendor",
    "ai_strategy",
    "hcltech_penetration",
    "consensus",
}


SOURCE_TIER_LABELS = {
    SourceTier.tier_1_official_financial: "Tier 1: official financial / filing evidence",
    SourceTier.tier_2_official_company: "Tier 2: official company / partner evidence",
    SourceTier.tier_3_reputable_context: "Tier 3: reputable external context",
    SourceTier.tier_4_directional_signal: "Tier 4: directional job / ecosystem signal",
    SourceTier.system: "System evidence",
    SourceTier.rejected: "Rejected source",
}

SECTION_SIGNAL_TYPES = {
    "company_overview": EvidenceSignalType.strategic_priority,
    "financial_trends": EvidenceSignalType.financial_metric,
    "recent_investments": EvidenceSignalType.investment,
    "partnerships_deals": EvidenceSignalType.partnership_deal,
    "account_priorities": EvidenceSignalType.strategic_priority,
    "it_spend": EvidenceSignalType.it_investment,
    "technology_stack": EvidenceSignalType.technology_stack,
    "footprint_hiring": EvidenceSignalType.hiring_footprint,
    "key_signals": EvidenceSignalType.news_signal,
    "outsourcing_vendor": EvidenceSignalType.vendor_outsourcing,
    "executives": EvidenceSignalType.executive_buying_center,
    "ai_strategy": EvidenceSignalType.ai_strategy,
    "hcltech_penetration": EvidenceSignalType.hcltech_opportunity,
    "consensus": EvidenceSignalType.consensus_move,
    "evidence_appendix": EvidenceSignalType.evidence_quality,
}

TABLE_BY_SIGNAL_TYPE = {
    EvidenceSignalType.financial_metric: "financial_metrics",
    EvidenceSignalType.investment: "investment_signals",
    EvidenceSignalType.partnership_deal: "partnership_signals",
    EvidenceSignalType.strategic_priority: "strategic_priorities",
    EvidenceSignalType.technology_stack: "technology_signals",
    EvidenceSignalType.hiring_footprint: "hiring_signals",
    EvidenceSignalType.it_investment: "it_investment_signals",
    EvidenceSignalType.news_signal: "news_signals",
    EvidenceSignalType.vendor_outsourcing: "vendor_signals",
    EvidenceSignalType.executive_buying_center: "executive_buying_center",
    EvidenceSignalType.ai_strategy: "ai_strategy_signals",
    EvidenceSignalType.hcltech_opportunity: "opportunity_hypotheses",
    EvidenceSignalType.consensus_move: "consensus_moves",
    EvidenceSignalType.evidence_quality: "evidence_quality",
}

TABLE_BY_SECTION = {
    "company_overview": "company_profile",
    "financial_trends": "financial_metrics",
    "recent_investments": "investment_signals",
    "partnerships_deals": "partnership_signals",
    "account_priorities": "strategic_priorities",
    "it_spend": "it_investment_signals",
    "technology_stack": "technology_signals",
    "footprint_hiring": "hiring_signals",
    "key_signals": "news_signals",
    "outsourcing_vendor": "vendor_signals",
    "executives": "executive_buying_center",
    "ai_strategy": "ai_strategy_signals",
    "hcltech_penetration": "opportunity_hypotheses",
    "consensus": "consensus_moves",
    "evidence_appendix": "evidence_quality",
}


def _source_haystack(source: EvidenceSource) -> str:
    return f"{source.title} {source.url} {source.publisher or ''}".lower()


def _coerce_source_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    match = ISO_DATE_RE.search(cleaned)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)
    match = MONTH_DATE_RE.search(cleaned)
    if match:
        month_name, day, year = match.groups()
        return datetime(int(year), MONTHS[month_name.lower()[:3]], max(1, int(day)), tzinfo=timezone.utc)
    return None


def _source_inferred_datetime(source: EvidenceSource) -> datetime | None:
    explicit = _coerce_source_datetime(source.published_at)
    if explicit:
        return explicit
    combined = f"{source.title} {source.url}"
    match = ISO_DATE_RE.search(combined)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)
    match = URL_YEAR_MONTH_RE.search(source.url)
    if match:
        year, month = (int(part) for part in match.groups())
        return datetime(year, month, 1, tzinfo=timezone.utc)
    match = MONTH_DATE_RE.search(combined)
    if match:
        month_name, day, year = match.groups()
        return datetime(int(year), MONTHS[month_name.lower()[:3]], max(1, int(day)), tzinfo=timezone.utc)
    return None


def _source_topic_years(source: EvidenceSource) -> list[int]:
    title_years = [int(year) for year in YEAR_RE.findall(source.title or "")]
    if title_years:
        return title_years
    slug = source.url.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
    return [int(year) for year in YEAR_RE.findall(slug)]


def _as_of_datetime(context: AgentContext) -> datetime:
    raw = context.report.generated_at or context.run.created_at
    return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)


def _recency_cutoff_months(context: AgentContext) -> int:
    return 12


def _month_delta(later: datetime, earlier: datetime) -> int:
    return max(0, (later.year - earlier.year) * 12 + (later.month - earlier.month))


def _is_recency_sensitive_section(section_id: str) -> bool:
    return section_id in RECENCY_SENSITIVE_SECTIONS


def _source_is_stale_for_section(context: AgentContext, source: EvidenceSource, section_id: str) -> bool:
    if not _is_recency_sensitive_section(section_id):
        return False
    if source.url.startswith("system://") or source.credibility == SourceCredibility.system:
        return False
    as_of = _as_of_datetime(context)
    topic_years = _source_topic_years(source)
    if topic_years and max(topic_years) <= as_of.year - 2:
        return True
    source_date = _source_inferred_datetime(source)
    if not source_date:
        return False
    return _month_delta(as_of, source_date) > _recency_cutoff_months(context)


def _source_recency_status(context: AgentContext, source: EvidenceSource, section_id: str | None = None) -> str:
    if source.url.startswith("system://") or source.credibility == SourceCredibility.system:
        return "system"
    source_date = _source_inferred_datetime(source)
    topic_years = _source_topic_years(source)
    if section_id and _source_is_stale_for_section(context, source, section_id):
        return "stale_baseline"
    if source_date:
        age_months = _month_delta(_as_of_datetime(context), source_date)
        return "recent" if age_months <= _recency_cutoff_months(context) else "historical_baseline"
    if topic_years:
        return "recent" if max(topic_years) >= _as_of_datetime(context).year - 1 else "historical_baseline"
    return "undated"


def _rank_source_ids_for_section(
    context: AgentContext,
    source_ids: list[str] | None,
    section_id: str,
    *,
    limit: int | None = None,
    include_stale_if_needed: bool = True,
) -> list[str]:
    if source_ids is None:
        return []
    source_by_id = {source.id: source for source in context.report.sources}
    deduped = _dedupe_preserve_order([source_id for source_id in source_ids if source_id in source_by_id])
    if not deduped:
        return []

    def sort_key(source_id: str) -> tuple[int, float, int, float, str]:
        source = source_by_id[source_id]
        source_date = _source_inferred_datetime(source)
        date_score = source_date.timestamp() if source_date else 0.0
        tier = source.source_tier or _infer_source_tier(source)
        tier_rank = {
            SourceTier.tier_1_official_financial: 0,
            SourceTier.tier_2_official_company: 1,
            SourceTier.tier_3_reputable_context: 2,
            SourceTier.tier_4_directional_signal: 3,
            SourceTier.system: 4,
            SourceTier.rejected: 5,
        }.get(tier, 3)
        if _source_is_stale_for_section(context, source, section_id):
            bucket = 4
        elif _source_recency_status(context, source, section_id) == "undated":
            bucket = 2
        elif source.url.startswith("system://"):
            bucket = 5
        else:
            bucket = 0
        return (bucket, -date_score, tier_rank, -source.credibility_score, source.title.lower())

    ranked = sorted(deduped, key=sort_key)
    if _is_recency_sensitive_section(section_id):
        non_stale = [source_id for source_id in ranked if not _source_is_stale_for_section(context, source_by_id[source_id], section_id)]
        if non_stale or not include_stale_if_needed:
            ranked = non_stale
    return ranked[:limit] if limit else ranked


def _infer_source_tier(source: EvidenceSource) -> SourceTier:
    haystack = _source_haystack(source)
    if source.credibility == SourceCredibility.rejected:
        return SourceTier.rejected
    if source.credibility == SourceCredibility.system or source.url.startswith("system://"):
        return SourceTier.system
    if source.credibility in {
        SourceCredibility.official_filing,
        SourceCredibility.investor_relations,
        SourceCredibility.earnings_transcript,
        SourceCredibility.regulator,
    }:
        return SourceTier.tier_1_official_financial
    if any(token in haystack for token in ["sec.gov", "annual report", "quarterly result", "earnings", "investor", "10-k", "10-q", "20-f", "r&d", "financial result"]):
        return SourceTier.tier_1_official_financial
    if source.credibility in {SourceCredibility.company_page, SourceCredibility.partner_page}:
        return SourceTier.tier_2_official_company
    if source.credibility == SourceCredibility.reputable_news:
        return SourceTier.tier_3_reputable_context
    if source.credibility == SourceCredibility.job_or_career_page:
        return SourceTier.tier_4_directional_signal
    if any(token in haystack for token in ["career", "jobs", "job-", "hiring", "workdayjobs", "greenhouse", "lever.co"]):
        return SourceTier.tier_4_directional_signal
    return SourceTier.tier_3_reputable_context


def _allowed_uses_for_source(source: EvidenceSource) -> list[str]:
    tier = source.source_tier or _infer_source_tier(source)
    uses: list[str] = []
    if tier == SourceTier.tier_1_official_financial:
        uses.extend(["exact_financial_metric", "financial_trend", "management_priority", "investment_amount_if_disclosed"])
    if tier == SourceTier.tier_2_official_company:
        uses.extend(["official_company_statement", "announced_partnership", "announced_investment", "product_or_ai_roadmap", "executive_priority"])
    if tier == SourceTier.tier_3_reputable_context:
        uses.extend(["reputable_news_signal", "external_context", "partnership_context", "market_signal"])
    if tier == SourceTier.tier_4_directional_signal:
        uses.extend(["hiring_signal", "technology_signal", "location_signal", "skills_signal"])
    if tier == SourceTier.system:
        uses.append("system_control")
    return _dedupe_preserve_order(uses)


def _enrich_source(source: EvidenceSource) -> EvidenceSource:
    source.source_tier = source.source_tier or _infer_source_tier(source)
    source.allowed_uses = _dedupe_preserve_order(source.allowed_uses + _allowed_uses_for_source(source))
    if source.source_tier == SourceTier.tier_1_official_financial:
        source.credibility_score = max(source.credibility_score, 0.82)
    elif source.source_tier == SourceTier.tier_2_official_company:
        source.credibility_score = max(source.credibility_score, 0.76)
    elif source.source_tier == SourceTier.tier_3_reputable_context:
        source.credibility_score = max(source.credibility_score, 0.70)
    return source


def _source_use_policy(source: EvidenceSource) -> str:
    tier = source.source_tier or _infer_source_tier(source)
    if tier == SourceTier.tier_1_official_financial:
        return "May support exact financial metrics and disclosed investment amounts when the excerpt contains the exact value."
    if tier == SourceTier.tier_2_official_company:
        return "May support official company statements, announced partnerships, announced investments, AI/product roadmap, customer wins, and executive priorities."
    if tier == SourceTier.tier_3_reputable_context:
        return "May support reputable external context and directional market signals; do not use alone for exact financial metrics."
    if tier == SourceTier.tier_4_directional_signal:
        return "May support directional hiring, skills, technology, and footprint signals; do not use for exact spend or headcount estimates."
    return "Internal/system evidence only."


def _system_source() -> EvidenceSource:
    return _enrich_source(EvidenceSource(
        url="system://market-research-portal/scaffold",
        title="Market Research Portal scaffold safeguard",
        publisher="Market Research Portal",
        credibility=SourceCredibility.system,
        credibility_score=1.0,
    ))


def _add_claim(context: AgentContext, section_id: str, text: str, claim_type: str, source_ids: list[str], confidence: float) -> str:
    normalized_text = " ".join(SOURCE_TOKEN_RE.sub("", text).replace("[]", "").split())
    normalized_sources = _rank_source_ids_for_section(context, list(dict.fromkeys(source_ids)), section_id, limit=12)
    source_set = set(normalized_sources)
    for existing in context.report.claims:
        existing_text = " ".join(SOURCE_TOKEN_RE.sub("", existing.text).replace("[]", "").split())
        if (
            existing.section_id == section_id
            and existing.claim_type == claim_type
            and existing_text == normalized_text
            and set(existing.evidence_source_ids) == source_set
        ):
            if existing.id not in context.report.research_anchor.claim_ids:
                context.report.research_anchor.claim_ids.append(existing.id)
            return existing.id
    claim = Claim(
        text=normalized_text,
        section_id=section_id,
        claim_type=claim_type,  # type: ignore[arg-type]
        evidence_source_ids=normalized_sources,
        confidence_score=confidence,
        verification_status="pending",
    )
    context.report.claims.append(claim)
    context.report.research_anchor.claim_ids.append(claim.id)
    _maybe_add_signal_for_claim(context, claim)
    return claim.id


def _preferred_source_ids(context: AgentContext, limit: int = 3) -> list[str]:
    non_system = [source.id for source in context.report.sources if not source.url.startswith("system://")]
    if non_system:
        return non_system[:limit]
    return [source.id for source in context.report.sources[:limit]]


def _section(context: AgentContext, section_id: str) -> ReportSection:
    return next(section for section in context.report.sections if section.id == section_id)


def _source_for_url(context: AgentContext, url: str) -> EvidenceSource | None:
    return next((source for source in context.report.sources if source.url == url), None)


def _attach_extracted_page(
    context: AgentContext,
    *,
    url: str,
    title: str,
    publisher: str | None,
    credibility: SourceCredibility,
    credibility_score: float,
    text: str,
    metadata: dict[str, str] | None = None,
) -> str:
    source = _source_for_url(context, url)
    if source is None:
        source = _enrich_source(EvidenceSource(
            url=url,
            title=title or url,
            publisher=publisher,
            published_at=(metadata or {}).get("publishedTime") or (metadata or {}).get("published_at"),
            credibility=credibility,
            credibility_score=credibility_score,
        ))
        context.report.sources.append(source)
        context.report.research_anchor.source_ids.append(source.id)
        context.report.research_anchor.raw_urls.append(source.url)
    elif title and source.title == source.url:
        source.title = title
        _enrich_source(source)
    else:
        _enrich_source(source)

    if text:
        snapshot = SourceSnapshot(source_id=source.id, text_excerpt=text[:14000], storage_uri=None)
        context.report.snapshots.append(snapshot)
        context.report.research_anchor.snapshot_ids.append(snapshot.id)
        source.snapshot_id = snapshot.id
    return source.id


def _snapshot_excerpt(context: AgentContext, source_id: str) -> str | None:
    for snapshot in reversed(context.report.snapshots):
        if snapshot.source_id == source_id and snapshot.text_excerpt:
            return snapshot.text_excerpt[:4500]
    return None


def _keyword_source_ids(context: AgentContext, keywords: list[str], limit: int = 8) -> list[str]:
    lowered = [keyword.lower() for keyword in keywords]
    selected: list[str] = []
    for source in context.report.sources:
        haystack = f"{source.title} {source.url} {source.publisher or ''}".lower()
        if any(keyword in haystack for keyword in lowered):
            selected.append(source.id)
        if len(selected) >= limit:
            break
    return selected


def _merge_source_ids(*groups: list[str], limit: int = 12) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for source_id in group:
            if source_id not in seen:
                seen.add(source_id)
                merged.append(source_id)
            if len(merged) >= limit:
                return merged
    return merged


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _dedupe_report_links(report: AccountReport) -> None:
    for section in report.sections:
        section.claim_ids = _dedupe_preserve_order(section.claim_ids)
    report.research_anchor.claim_ids = _dedupe_preserve_order(report.research_anchor.claim_ids)
    report.research_anchor.source_ids = _dedupe_preserve_order(report.research_anchor.source_ids)
    report.research_anchor.snapshot_ids = _dedupe_preserve_order(report.research_anchor.snapshot_ids)
    report.research_anchor.signal_ids = _dedupe_preserve_order(report.research_anchor.signal_ids)
    report.research_anchor.table_row_ids = _dedupe_preserve_order(report.research_anchor.table_row_ids)
    report.research_anchor.raw_urls = _dedupe_preserve_order(report.research_anchor.raw_urls)


def _dedupe_report_claims(report: AccountReport) -> None:
    seen: dict[tuple[str, str, str, tuple[str, ...]], str] = {}
    id_map: dict[str, str] = {}
    deduped: list[Claim] = []
    for claim in report.claims:
        claim.text = " ".join(SOURCE_TOKEN_RE.sub("", claim.text).replace("[]", "").split())
        claim.evidence_source_ids = _dedupe_preserve_order(claim.evidence_source_ids)
        key = (claim.section_id, claim.claim_type, claim.text, tuple(sorted(claim.evidence_source_ids)))
        if key in seen:
            id_map[claim.id] = seen[key]
            continue
        seen[key] = claim.id
        id_map[claim.id] = claim.id
        deduped.append(claim)
    report.claims = deduped
    for section in report.sections:
        section.claim_ids = [id_map.get(claim_id, claim_id) for claim_id in section.claim_ids]
    report.research_anchor.claim_ids = [id_map.get(claim_id, claim_id) for claim_id in report.research_anchor.claim_ids]
    signal_seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    deduped_signals: list[EvidenceSignal] = []
    for signal in report.evidence_signals:
        signal.claim_ids = _dedupe_preserve_order([id_map.get(claim_id, claim_id) for claim_id in signal.claim_ids])
        signal.source_ids = _dedupe_preserve_order(signal.source_ids)
        key = (signal.section_id, signal.signal_type.value, signal.title, tuple(sorted(signal.source_ids)))
        if key in signal_seen:
            continue
        signal_seen.add(key)
        deduped_signals.append(signal)
    report.evidence_signals = deduped_signals
    report.research_anchor.signal_ids = [signal.id for signal in deduped_signals]
    _dedupe_report_links(report)


def _table_name_for_signal(signal_type: EvidenceSignalType) -> str:
    return TABLE_BY_SIGNAL_TYPE.get(signal_type, "all_evidence_items")


def _table_name_for_section(section_id: str) -> str:
    return TABLE_BY_SECTION.get(section_id, "all_evidence_items")


def _table_detail(text: str | None, limit: int = 3500) -> str:
    cleaned = _strip_internal_source_tokens(text or "")
    return cleaned if len(cleaned) <= limit else cleaned[: max(0, limit - 3)].rstrip() + "..."


def _append_table_row(rows: list[EvidenceTableRow], row: EvidenceTableRow, seen: set[tuple]) -> None:
    key = (
        row.table_name,
        row.row_type,
        row.section_id,
        row.title,
        row.detail,
        tuple(sorted(row.source_ids)),
        tuple(sorted(row.snapshot_ids)),
        tuple(sorted(row.claim_ids)),
        tuple(sorted(row.signal_ids)),
        tuple(sorted(row.extracted_value_ids)),
    )
    if key in seen:
        return
    seen.add(key)
    rows.append(row)


def _evidence_table_counts(report: AccountReport) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in report.evidence_table_rows:
        counts[row.table_name] = counts.get(row.table_name, 0) + 1
    return dict(sorted(counts.items()))


def _rows_for_source(report: AccountReport, source_id: str, limit: int = 8) -> list[dict]:
    rows: list[dict] = []
    for row in report.evidence_table_rows:
        if source_id not in row.source_ids:
            continue
        rows.append(
            {
                "table_name": row.table_name,
                "row_type": row.row_type,
                "title": row.title,
                "detail": row.detail[:900],
                "confidence_score": row.confidence_score,
                "source_ids": row.source_ids[:5],
                "claim_ids": row.claim_ids[:5],
                "signal_ids": row.signal_ids[:5],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def refresh_evidence_tables(context: AgentContext) -> None:
    report = context.report
    sources_by_id = {source.id: source for source in report.sources}
    snapshots_by_source: dict[str, list[SourceSnapshot]] = {}
    for snapshot in report.snapshots:
        snapshots_by_source.setdefault(snapshot.source_id, []).append(snapshot)

    rows: list[EvidenceTableRow] = []
    seen: set[tuple] = set()

    for source in report.sources:
        tier = source.source_tier or _infer_source_tier(source)
        snapshots = snapshots_by_source.get(source.id, [])
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name="source_catalog",
                row_type="source",
                title=_table_detail(source.title or source.url, limit=180),
                detail=_table_detail(f"{source.publisher or 'Unknown publisher'} | {source.url}", limit=1000),
                normalized_fields={
                    "url": source.url,
                    "publisher": source.publisher,
                    "published_at": source.published_at,
                    "inferred_source_date": _source_inferred_datetime(source).date().isoformat() if _source_inferred_datetime(source) else None,
                    "topic_years": _source_topic_years(source),
                    "recency_status": _source_recency_status(context, source),
                    "credibility": source.credibility.value,
                    "credibility_score": source.credibility_score,
                    "source_tier": tier.value,
                    "allowed_uses": source.allowed_uses or _allowed_uses_for_source(source),
                    "snapshot_count": len(snapshots),
                },
                source_ids=[source.id],
                snapshot_ids=[snapshot.id for snapshot in snapshots],
                source_tier=tier,
                confidence_score=source.credibility_score,
                include_in_analysis=source.url.startswith("http"),
            ),
            seen,
        )

    for snapshot in report.snapshots:
        source = sources_by_id.get(snapshot.source_id)
        tier = (source.source_tier or _infer_source_tier(source)) if source else None
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name="source_snapshots",
                row_type="snapshot",
                title=_table_detail(source.title if source else snapshot.source_id, limit=180),
                detail=_table_detail(snapshot.text_excerpt, limit=3500),
                normalized_fields={
                    "captured_at": snapshot.captured_at.isoformat(),
                    "storage_uri": snapshot.storage_uri,
                    "checksum": snapshot.checksum,
                    "source_url": source.url if source else None,
                },
                source_ids=[snapshot.source_id],
                snapshot_ids=[snapshot.id],
                source_tier=tier,
                confidence_score=source.credibility_score if source else 0.5,
                include_in_analysis=bool(snapshot.text_excerpt),
            ),
            seen,
        )

    for value in report.extracted_values:
        source = sources_by_id.get(value.source_id or "")
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name="financial_metrics" if value.exact else "all_evidence_items",
                row_type="extracted_value",
                title=_table_detail(value.label, limit=160),
                detail=_table_detail(str(value.value) if value.value is not None else value.unavailable_reason, limit=1000),
                normalized_fields={
                    "value": value.value,
                    "unit": value.unit,
                    "period": value.period,
                    "exact": value.exact,
                    "unavailable_reason": value.unavailable_reason,
                },
                source_ids=[value.source_id] if value.source_id else [],
                extracted_value_ids=[value.id],
                source_tier=(source.source_tier or _infer_source_tier(source)) if source else None,
                confidence_score=1.0 if value.exact and value.value is not None else 0.55,
                include_in_analysis=value.value is not None,
            ),
            seen,
        )

    for claim in report.claims:
        if claim.claim_type == "unavailable":
            table_name = "unsupported_or_not_disclosed"
        elif _is_policy_or_guardrail_claim(claim.text):
            table_name = "evidence_quality"
        else:
            table_name = _table_name_for_section(claim.section_id)
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name=table_name,
                row_type="claim",
                section_id=claim.section_id,
                title=_claim_headline_text(claim.text, limit=160),
                detail=_table_detail(claim.text, limit=2000),
                normalized_fields={
                    "claim_type": claim.claim_type,
                    "verification_status": claim.verification_status,
                    "confidence_score": claim.confidence_score,
                    "freshness_sensitive": _is_recency_sensitive_section(claim.section_id),
                    "stale_only_evidence": claim.id in _stale_sensitive_claim_ids(context),
                },
                source_ids=claim.evidence_source_ids,
                claim_ids=[claim.id],
                confidence_score=claim.confidence_score,
                include_in_analysis=claim.claim_type != "unavailable" and not _is_policy_or_guardrail_claim(claim.text),
            ),
            seen,
        )

    for signal in report.evidence_signals:
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name=_table_name_for_signal(signal.signal_type),
                row_type="signal",
                section_id=signal.section_id,
                title=_table_detail(signal.title, limit=160),
                detail=_table_detail(signal.detail, limit=2200),
                normalized_fields={
                    "signal_type": signal.signal_type.value,
                    "signal_strength": signal.signal_strength,
                    "confidence_score": signal.confidence_score,
                },
                source_ids=signal.source_ids,
                claim_ids=signal.claim_ids,
                signal_ids=[signal.id],
                signal_type=signal.signal_type,
                confidence_score=signal.confidence_score,
                include_in_analysis=signal.signal_strength != "unsupported",
            ),
            seen,
        )

    for section in report.sections:
        if not section.summary or section.summary == "Pending source-backed research.":
            continue
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name="section_summaries",
                row_type="section_summary",
                section_id=section.id,
                title=section.title,
                detail=_table_detail(section.summary, limit=1600),
                normalized_fields={
                    "status": section.status,
                    "confidence_score": section.confidence_score,
                    "mapped_claims": len(section.claim_ids),
                },
                claim_ids=section.claim_ids,
                confidence_score=section.confidence_score,
                include_in_analysis=section.status != "unavailable",
            ),
            seen,
        )

    for check in report.quality_checks:
        _append_table_row(
            rows,
            EvidenceTableRow(
                table_name="quality_checks",
                row_type="quality_check",
                title=check.name,
                detail=_table_detail(check.message, limit=1200),
                normalized_fields={
                    "passed": check.passed,
                    "severity": check.severity,
                    "checked_at": check.checked_at.isoformat(),
                },
                confidence_score=1.0 if check.passed else 0.0,
                include_in_analysis=False,
            ),
            seen,
        )

    report.evidence_table_rows = rows
    report.research_anchor.table_row_ids = [row.id for row in rows]
    _dedupe_report_links(report)


def _strip_internal_source_tokens(text: str) -> str:
    cleaned = re.sub(r"\[[^\]]*src_[0-9a-f]{8,16}[^\]]*\]", "", text)
    cleaned = SOURCE_TOKEN_RE.sub("", cleaned)
    cleaned = re.sub(r"\[\s*[,;:\s]*\]", "", cleaned)
    return " ".join(cleaned.replace("[]", "").split())


def _replace_quality_check(context: AgentContext, check: QualityCheck) -> None:
    context.report.quality_checks = [existing for existing in context.report.quality_checks if existing.name != check.name]
    context.report.quality_checks.append(check)


def _section_claims(context: AgentContext, section_id: str) -> list[Claim]:
    section = _section(context, section_id)
    claim_ids = set(section.claim_ids)
    return [claim for claim in context.report.claims if claim.id in claim_ids]


def _reader_ready_claim_text(text: str) -> str:
    return _strip_internal_source_tokens(text).strip()


def _shorten_reader_text(text: str, limit: int = 150) -> str:
    cleaned = " ".join(_reader_ready_claim_text(text).split()).rstrip(".")
    return cleaned if len(cleaned) <= limit else cleaned[: max(0, limit - 3)].rstrip() + "..."


def _claim_headline_text(text: str, limit: int = 145) -> str:
    cleaned = " ".join(_reader_ready_claim_text(text).split()).rstrip(".")
    cleaned = re.split(
        r";\s*(?:the\s+)?provided records? (?:do|does) not|;\s*no exact|;\s*missing fields|;\s*the source excerpt",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return cleaned if len(cleaned) <= limit else cleaned[: max(0, limit - 3)].rstrip() + "..."


def _is_policy_or_guardrail_claim(text: str) -> bool:
    lowered = text.lower()
    policy_phrases = [
        "must be",
        "requires",
        "require ",
        "only when",
        "do not ",
        "not estimated",
        "should be extracted",
        "generated only",
        "guidance should",
        "assessment must",
        "unavailable until",
        "marked unavailable",
        "exact public evidence",
        "missing fields",
        "source ids",
        "policy",
        "source-backed",
        "source grounded",
    ]
    return any(phrase in lowered for phrase in policy_phrases)


def _signal_type_for_section(section_id: str) -> EvidenceSignalType:
    return SECTION_SIGNAL_TYPES.get(section_id, EvidenceSignalType.evidence_quality)


def _signal_strength_for_claim(claim: Claim) -> str:
    if claim.claim_type == "unavailable":
        return "unsupported"
    if claim.claim_type in {"recommendation", "inference"}:
        return "inferred"
    if claim.section_id == "financial_trends":
        return "exact"
    return "directional"


def _maybe_add_signal_for_claim(context: AgentContext, claim: Claim) -> None:
    if claim.claim_type == "unavailable" or not claim.evidence_source_ids:
        return
    if _is_policy_or_guardrail_claim(claim.text):
        return
    existing = next((signal for signal in context.report.evidence_signals if claim.id in signal.claim_ids), None)
    if existing:
        return
    title = _claim_headline_text(claim.text, limit=110)
    if not title:
        return
    signal = EvidenceSignal(
        section_id=claim.section_id,
        signal_type=_signal_type_for_section(claim.section_id),
        title=title,
        detail=_reader_ready_claim_text(claim.text),
        signal_strength=_signal_strength_for_claim(claim),  # type: ignore[arg-type]
        source_ids=claim.evidence_source_ids,
        claim_ids=[claim.id],
        confidence_score=claim.confidence_score,
    )
    context.report.evidence_signals.append(signal)
    context.report.research_anchor.signal_ids.append(signal.id)


def _source_ids_from_signals(
    context: AgentContext,
    *,
    signal_types: set[EvidenceSignalType] | None = None,
    keywords: list[str] | None = None,
    limit: int = 30,
) -> list[str]:
    lowered = [keyword.lower() for keyword in (keywords or [])]
    source_ids: list[str] = []
    for signal in sorted(context.report.evidence_signals, key=lambda item: item.confidence_score, reverse=True):
        if signal_types and signal.signal_type not in signal_types:
            continue
        haystack = f"{signal.title} {signal.detail}".lower()
        if lowered and not any(keyword in haystack for keyword in lowered):
            continue
        for source_id in signal.source_ids:
            if source_id not in source_ids:
                source_ids.append(source_id)
            if len(source_ids) >= limit:
                return source_ids
    return source_ids


def _evidence_signal_summary(context: AgentContext, limit: int = 12) -> list[dict]:
    return [
        {
            "signal_type": signal.signal_type.value,
            "title": signal.title,
            "strength": signal.signal_strength,
            "confidence_score": signal.confidence_score,
            "source_ids": signal.source_ids[:5],
        }
        for signal in sorted(context.report.evidence_signals, key=lambda item: item.confidence_score, reverse=True)[:limit]
    ]


def _normalize_evidence_language(text: str) -> str:
    replacements = {
        "UNAVAILABLE": "Exact value not disclosed",
        "unavailable until official filings or investor materials are extracted by a live provider": "exact value not found in the extracted official evidence for this run",
        "Pending extraction of an exact revenue value from annual, quarterly, investor, or filing evidence.": "Exact revenue value not found in the extracted official financial evidence for this run.",
        "Pending extraction of an exact R&D value from annual, quarterly, investor, or filing evidence.": "Exact R&D value not found in the extracted official financial evidence for this run.",
        "If the evidence is thin, say exactly what is unavailable.": "If the evidence is thin, distinguish exact values not disclosed from directional signals available.",
        "Signal validation policy is configured.": "Key signals are reported when supported by official announcements or reputable news within the selected freshness window.",
    }
    cleaned = text
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(
        r"\b(unavailable)\b",
        "not disclosed in the extracted evidence",
        cleaned,
        flags=re.IGNORECASE,
    ) if "unavailable until" in cleaned.lower() else cleaned
    return cleaned


def _normalize_section_evidence_language(context: AgentContext, section: ReportSection) -> None:
    section.summary = _normalize_evidence_language(section.summary)
    synthesis = section.content.get("synthesis") if isinstance(section.content, dict) else None
    if isinstance(synthesis, dict) and isinstance(synthesis.get("bullets"), list):
        synthesis["bullets"] = [
            _normalize_evidence_language(bullet) if isinstance(bullet, str) else bullet
            for bullet in synthesis["bullets"]
        ]
    useful_claims = [
        claim
        for claim in _section_claims(context, section.id)
        if claim.claim_type in {"fact", "inference", "recommendation"} and claim.evidence_source_ids
    ]
    if section.status == "unavailable" and useful_claims:
        section.status = "partial"


def _stale_sensitive_claim_ids(context: AgentContext) -> list[str]:
    source_by_id = {source.id: source for source in context.report.sources}
    stale_claims: list[str] = []
    for claim in context.report.claims:
        if claim.claim_type == "unavailable" or _is_policy_or_guardrail_claim(claim.text):
            continue
        if not _is_recency_sensitive_section(claim.section_id) or not claim.evidence_source_ids:
            continue
        linked_sources = [source_by_id[source_id] for source_id in claim.evidence_source_ids if source_id in source_by_id]
        if linked_sources and all(_source_is_stale_for_section(context, source, claim.section_id) for source in linked_sources):
            stale_claims.append(claim.id)
    return stale_claims


def _source_ids_from_claims(
    context: AgentContext,
    *,
    section_ids: set[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 28,
) -> list[str]:
    lowered = [keyword.lower() for keyword in (keywords or [])]
    source_ids: list[str] = []
    for claim in context.report.claims:
        if _is_policy_or_guardrail_claim(claim.text):
            continue
        if section_ids and claim.section_id not in section_ids:
            continue
        haystack = claim.text.lower()
        if lowered and not any(keyword in haystack for keyword in lowered):
            continue
        for source_id in claim.evidence_source_ids:
            if source_id not in source_ids:
                source_ids.append(source_id)
            if len(source_ids) >= limit:
                return source_ids
    return source_ids


def _prioritized_public_sources(context: AgentContext, limit: int) -> list[EvidenceSource]:
    priority_terms = [
        "annual",
        "quarter",
        "results",
        "investor",
        "financial",
        "press",
        "newsroom",
        "partnership",
        "collaborat",
        "investment",
        "acquisition",
        "ai",
        "cloud",
        "career",
        "jobs",
        "managed-services",
        "managed services",
        "outsourcing",
        "consulting",
    ]
    public_sources = [source for source in context.report.sources if source.url.startswith("http")]
    seen_urls: set[str] = set()
    deduped: list[EvidenceSource] = []
    for source in public_sources:
        normalized_url = source.url.split("#", 1)[0].rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduped.append(source)

    def score(source: EvidenceSource) -> tuple[int, float]:
        haystack = f"{source.title} {source.url} {source.publisher or ''}".lower()
        keyword_score = sum(1 for term in priority_terms if term in haystack)
        official_score = 3 if any(term in haystack for term in ["official", "investor", "press-release", "press-releases", "newsroom", "annual-report"]) else 0
        snapshot_penalty = -2 if source.snapshot_id else 0
        return (keyword_score + official_score + snapshot_penalty, source.credibility_score)

    return sorted(deduped, key=score, reverse=True)[:limit]


def _fallback_section_from_related_claims(
    context: AgentContext,
    section_id: str,
    *,
    source_section_ids: set[str],
    keywords: list[str],
    summary_prefix: str,
    claim_prefix: str,
    claim_type: str = "inference",
    max_claims: int = 6,
    min_confidence: float = 0.72,
    caveat: str | None = None,
) -> bool:
    lowered = [keyword.lower() for keyword in keywords]
    candidate_claims = [
        claim
        for claim in context.report.claims
        if claim.section_id in source_section_ids
        and claim.claim_type in {"fact", "inference", "recommendation"}
        and claim.evidence_source_ids
        and not _is_policy_or_guardrail_claim(claim.text)
        and any(keyword in claim.text.lower() for keyword in lowered)
    ]
    if not candidate_claims:
        return False

    candidate_claims = sorted(candidate_claims, key=lambda claim: claim.confidence_score, reverse=True)
    section = _section(context, section_id)
    headlines: list[str] = []
    for claim in candidate_claims[:max_claims]:
        headline = _claim_headline_text(claim.text, limit=170)
        if not headline:
            continue
        headlines.append(headline)
        new_claim_id = _add_claim(
            context,
            section_id,
            f"{claim_prefix}: {headline}",
            claim_type,
            claim.evidence_source_ids,
            min(0.9, max(0.62, claim.confidence_score)),
        )
        section.claim_ids.append(new_claim_id)

    if not headlines:
        return False
    section.summary = f"{summary_prefix}: " + "; ".join(headlines[:4]) + "."
    if caveat:
        section.summary += f" {caveat}"
    section.content["synthesis"] = {
        "provider": "cross_section_evidence_fallback",
        "model": "deterministic_claim_synthesis",
        "reasoning_effort": "policy",
        "bullets": headlines[:max_claims],
    }
    section.status = "partial"
    section.confidence_score = max(section.confidence_score, min_confidence)
    return True


def _fallback_section_from_claims(
    context: AgentContext,
    section_id: str,
    *,
    prefix: str,
    max_claims: int = 4,
    min_confidence: float = 0.68,
    caveat: str | None = None,
) -> bool:
    section = _section(context, section_id)
    useful_claims = [
        claim
        for claim in _section_claims(context, section_id)
        if claim.claim_type in {"fact", "inference", "recommendation"}
        and claim.evidence_source_ids
        and not claim.text.lower().startswith("recent investment details require")
    ]
    if not useful_claims:
        return False
    useful_claims = sorted(useful_claims, key=lambda claim: claim.confidence_score, reverse=True)
    claim_texts = [_reader_ready_claim_text(claim.text).rstrip(".") for claim in useful_claims[:max_claims]]
    summary_texts = [_claim_headline_text(claim.text) for claim in useful_claims[:3]]
    section.summary = f"{prefix}: " + "; ".join(summary_texts) + "."
    if caveat:
        section.summary += f" {caveat}"
    synthesis = section.content.get("synthesis") if isinstance(section.content, dict) else None
    if isinstance(synthesis, dict):
        synthesis["bullets"] = claim_texts
    else:
        section.content["synthesis"] = {"bullets": claim_texts}
    section.status = "partial"
    section.confidence_score = max(section.confidence_score, min_confidence)
    return True


def _apply_hcl_strategy_playbook(context: AgentContext, source_ids: list[str]) -> None:
    section = _section(context, "hcltech_penetration")
    premise_sections = {
        "recent_investments",
        "partnerships_deals",
        "account_priorities",
        "it_spend",
        "technology_stack",
        "footprint_hiring",
        "key_signals",
        "outsourcing_vendor",
        "executives",
        "ai_strategy",
    }
    useful_claims = [
        claim
        for claim in context.report.claims
        if claim.section_id in premise_sections
        and claim.claim_type in {"fact", "inference", "recommendation"}
        and claim.evidence_source_ids
        and not _is_policy_or_guardrail_claim(claim.text)
    ]
    if not useful_claims:
        return
    corpus = " ".join(
        [claim.text.lower() for claim in useful_claims]
        + [f"{signal.title} {signal.detail}".lower() for signal in context.report.evidence_signals]
    )

    play_catalog = [
        (
            "AI-led productivity and process automation pilot",
            ["ai", "artificial intelligence", "genai", "generative ai", "automation", "copilot", "agentic"],
        ),
        (
            "cloud, data, and platform modernization discovery",
            ["cloud", "data", "analytics", "platform", "modernization", "migration", "database", "lakehouse"],
        ),
        (
            "cyber resilience, risk, and compliance modernization",
            ["security", "cyber", "risk", "compliance", "privacy", "zero trust", "resilience", "regulatory"],
        ),
        (
            "managed operations and cost-optimization pilot",
            ["managed services", "operations", "cost", "efficiency", "optimization", "vendor consolidation", "run cost"],
        ),
        (
            "digital customer, commerce, and service experience modernization",
            ["customer", "commerce", "crm", "marketing", "sales", "support", "experience", "omnichannel"],
        ),
        (
            "ERP, finance, and enterprise process modernization",
            ["erp", "sap", "oracle", "finance", "procurement", "supply chain", "back office", "shared services"],
        ),
        (
            "product engineering and software delivery acceleration",
            ["engineering", "software", "devops", "product", "platform engineering", "developer", "application"],
        ),
        (
            "workforce skills, operating model, and change enablement",
            ["hiring", "talent", "skills", "workforce", "training", "reskilling", "operating model"],
        ),
    ]

    industry_overlays = [
        (
            "banking / insurance",
            ["bank", "banking", "insurance", "payments", "wealth", "lending", "credit", "capital markets"],
            "regulated data, risk, and AI governance workstream",
        ),
        (
            "retail / consumer",
            ["retail", "commerce", "consumer", "store", "loyalty", "merchandising", "supply chain"],
            "customer data, commerce, and supply-chain intelligence workstream",
        ),
        (
            "healthcare / life sciences",
            ["healthcare", "life sciences", "patient", "provider", "payer", "clinical", "pharma", "medical"],
            "trusted data, compliant automation, and experience modernization workstream",
        ),
        (
            "manufacturing / industrial",
            ["manufacturing", "factory", "industrial", "plant", "supply chain", "plm", "engineering", "asset"],
            "smart operations, engineering, and supply-chain modernization workstream",
        ),
        (
            "technology / software",
            ["software", "saas", "platform", "developer", "product", "cloud service", "database"],
            "platform engineering and product modernization workstream",
        ),
        (
            "telecom",
            ["telecom", "telecommunications", "5g", "6g", "ran", "oss", "bss", "network operator"],
            "network, OSS/BSS, and service-operations modernization workstream",
        ),
    ]

    plays: list[str] = [
        play for play, keywords in play_catalog if any(keyword in corpus for keyword in keywords)
    ]
    overlays = [
        overlay for _, keywords, overlay in industry_overlays if any(keyword in corpus for keyword in keywords)
    ]
    for overlay in reversed(overlays[:2]):
        if overlay not in plays:
            plays.insert(0, overlay)
    if not plays:
        plays.append("account-specific modernization pilot derived from verified priorities")

    evidence_headlines = [_claim_headline_text(claim.text, limit=140) for claim in useful_claims[:4]]
    section.summary = (
        "Recommended HCLTech penetration motion: lead with "
        + "; ".join(plays[:3])
        + ". First 90 days: validate the relevant buying center, run a co-innovation discovery workshop, and shape one pilot around a measurable business, technology, or operating outcome. Validate commercial timing with the account team before client use."
    )
    section.content["synthesis"] = {
        "provider": "cross_section_strategy_playbook",
        "model": "deterministic_claim_synthesis",
        "reasoning_effort": "policy",
        "bullets": [f"Entry play: {play}" for play in plays[:4]]
        + [f"Evidence premise: {headline}" for headline in evidence_headlines[:4]],
    }
    section.status = "partial"
    section.confidence_score = max(section.confidence_score, 0.72)
    for play in plays[:4]:
        claim_id = _add_claim(
            context,
            "hcltech_penetration",
            f"HCLTech recommended entry play: {play}",
            "recommendation",
            source_ids[:8],
            0.72,
        )
        section.claim_ids.append(claim_id)


def _section_slide_bullets(context: AgentContext, section: ReportSection, *, limit: int = 5) -> list[str]:
    bullets: list[str] = []
    synthesis = section.content.get("synthesis") if isinstance(section.content, dict) else None
    if isinstance(synthesis, dict):
        for bullet in synthesis.get("bullets") or []:
            if isinstance(bullet, str) and bullet.strip():
                bullets.append(_reader_ready_claim_text(bullet))
    if section.summary:
        bullets.insert(0, _reader_ready_claim_text(section.summary))
    for claim in sorted(_section_claims(context, section.id), key=lambda item: item.confidence_score, reverse=True):
        if claim.claim_type == "unavailable":
            continue
        text = _reader_ready_claim_text(claim.text)
        if text and text not in bullets:
            bullets.append(text)
    unique_bullets: list[str] = []
    seen: set[str] = set()
    for bullet in bullets:
        normalized = bullet.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_bullets.append(bullet)
        if len(unique_bullets) >= limit:
            break
    return unique_bullets or ["No source-backed synthesis available yet."]


async def _extract_sources(context: AgentContext, source_ids: list[str], *, limit: int = 5) -> int:
    firecrawl = context.providers.extraction_providers()[0]
    by_id = {source.id: source for source in context.report.sources}
    targets = [
        source
        for source_id in source_ids
        if (source := by_id.get(source_id))
        and source.url.startswith("http")
        and not source.snapshot_id
    ][:limit]
    captured = 0
    for source in targets:
        try:
            page = await firecrawl.extract_url(source.url)
        except Exception:
            continue
        if not page.text:
            continue
        _attach_extracted_page(
            context,
            url=source.url,
            title=page.title or source.title,
            publisher=page.metadata.get("publisher") or source.publisher,
            credibility=source.credibility,
            credibility_score=source.credibility_score,
            text=page.text,
            metadata=page.metadata,
        )
        captured += 1
    if source_ids:
        _replace_quality_check(
            context,
            QualityCheck(
                name="section_source_extraction",
                passed=captured > 0 or not targets,
                severity="warning" if targets and captured == 0 else "info",
                message=f"Captured {captured} section-specific source snapshots from {len(targets)} targets.",
            )
        )
    return captured


async def _discover(context: AgentContext, query: str, credibility: SourceCredibility, score: float = 0.72, limit: int = 4) -> list[str]:
    provider = context.providers.search_provider()
    results = await provider.search(query)
    source_ids: list[str] = []
    for result in results[:limit]:
        existing = _source_for_url(context, result.url)
        if existing:
            if result.title and (not existing.title or existing.title == existing.url):
                existing.title = result.title
            if result.publisher and not existing.publisher:
                existing.publisher = result.publisher
            existing.credibility_score = max(existing.credibility_score, score)
            _enrich_source(existing)
            source_ids.append(existing.id)
            continue
        source_credibility = SourceCredibility.system if result.url.startswith("system://") else credibility
        discovered = _enrich_source(EvidenceSource(
            url=result.url,
            title=result.title,
            publisher=result.publisher,
            published_at=result.published_at,
            credibility=source_credibility,
            credibility_score=1 if source_credibility == SourceCredibility.system else score,
        ))
        context.report.sources.append(discovered)
        context.report.research_anchor.source_ids.append(discovered.id)
        context.report.research_anchor.raw_urls.append(discovered.url)
        source_ids.append(discovered.id)
    return source_ids


async def _discover_many(
    context: AgentContext,
    query_plan: list[tuple[str, SourceCredibility, float, int]],
) -> list[str]:
    results = await asyncio.gather(
        *[
            _discover(context, query, credibility, score=score, limit=limit)
            for query, credibility, score, limit in query_plan
        ],
        return_exceptions=True,
    )
    discovered: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        discovered.extend(result)
    return discovered


def _evidence_payload(context: AgentContext, source_ids: list[str] | None = None, section_id: str | None = None) -> list[dict]:
    sources = context.report.sources
    source_filter = set(source_ids or [])
    if source_ids is not None:
        sources = [source for source in sources if source.id in source_filter]
    elif section_id and _is_recency_sensitive_section(section_id):
        ranked_ids = _rank_source_ids_for_section(
            context,
            [source.id for source in context.report.sources],
            section_id,
            limit=60,
            include_stale_if_needed=False,
        )
        source_filter = set(ranked_ids)
        sources = [source for source in context.report.sources if source.id in source_filter]
    else:
        sources = sorted(sources, key=lambda source: (source.snapshot_id is None, source.url.startswith("system://")))
    if not sources and source_ids is None:
        sources = context.report.sources[:10]
    claims_by_source: dict[str, list[str]] = {}
    for claim in context.report.claims:
        for source_id in claim.evidence_source_ids:
            claims_by_source.setdefault(source_id, []).append(claim.text)
    signals_by_source: dict[str, list[dict]] = {}
    for signal in context.report.evidence_signals:
        signal_record = {
            "signal_type": signal.signal_type.value,
            "title": signal.title,
            "strength": signal.signal_strength,
            "confidence_score": signal.confidence_score,
        }
        for source_id in signal.source_ids:
            signals_by_source.setdefault(source_id, []).append(signal_record)
    return [
        {
            "id": source.id,
            "title": source.title,
            "url": source.url,
            "publisher": source.publisher,
            "published_at": source.published_at,
            "credibility": source.credibility.value,
            "credibility_score": source.credibility_score,
            "source_tier": (source.source_tier or _infer_source_tier(source)).value,
            "source_tier_label": SOURCE_TIER_LABELS.get(source.source_tier or _infer_source_tier(source), "Unclassified source"),
            "allowed_uses": source.allowed_uses or _allowed_uses_for_source(source),
            "source_use_policy": _source_use_policy(source),
            "recency_status": _source_recency_status(context, source, section_id),
            "inferred_source_date": _source_inferred_datetime(source).date().isoformat() if _source_inferred_datetime(source) else None,
            "freshness_policy": (
                "Freshness-sensitive section: use sources from the last 12 months when available; older 2024-style sources are historical baseline only."
                if section_id and _is_recency_sensitive_section(section_id)
                else "Baseline sources may be used where appropriate."
            ),
            "snapshot_excerpt": _snapshot_excerpt(context, source.id),
            "related_existing_claims": claims_by_source.get(source.id, [])[:8],
            "related_evidence_signals": signals_by_source.get(source.id, [])[:8],
            "related_table_rows": _rows_for_source(context.report, source.id, limit=10),
            "evidence_table_counts": _evidence_table_counts(context.report),
        }
        for source in sources[:60]
    ]


async def _synthesize_into_section(
    context: AgentContext,
    agent: Agent,
    section_id: str,
    instructions: str,
    source_ids: list[str] | None = None,
) -> SynthesisResult:
    section = _section(context, section_id)
    ranked_source_ids = (
        _rank_source_ids_for_section(context, source_ids, section_id, limit=60, include_stale_if_needed=False)
        if source_ids is not None
        else None
    )
    result = await context.providers.synthesis_provider().synthesize_section(
        company_name=context.run.company_name,
        section_id=section.id,
        section_title=section.title,
        agent_name=agent.name,
        model=agent.model,
        reasoning_effort=agent.reasoning_effort,
        evidence=_evidence_payload(context, ranked_source_ids, section_id=section_id),
        instructions=(
            instructions
            + (
                "\nFreshness rule: for this freshness-sensitive section, use sources from the latest 12 months when available. "
                "Treat older annual reports, FY/Q4 pages, and 2024-era material as historical baseline only; do not use them as primary support for recent investments, partnerships, IT-spend signals, AI moves, or account recommendations."
                if _is_recency_sensitive_section(section_id)
                else ""
            )
        ),
    )
    check_name = f"{section_id}_synthesis_call"
    _replace_quality_check(
        context,
        QualityCheck(
            name=check_name,
            passed=result.error is None,
            severity=(
                "blocker"
                if result.error and context.run.mode == ResearchMode.deep and section_id in {"hcltech_penetration", "consensus", "company_overview"}
                else "warning"
                if result.error
                else "info"
            ),
            message=(
                f"{agent.name} used {result.provider} with model={agent.model}, reasoning={agent.reasoning_effort}."
                if result.error is None
                else f"{agent.name} synthesis failed via {result.provider}: {result.error[:220]}"
            ),
        )
    )
    if result.error:
        return result

    if result.summary:
        section.summary = _strip_internal_source_tokens(result.summary)
    section.content["synthesis"] = {
        "provider": result.provider,
        "model": agent.model,
        "reasoning_effort": agent.reasoning_effort,
        "bullets": [_strip_internal_source_tokens(bullet) for bullet in result.bullets],
        "response_id": result.raw_response_id,
    }
    section.status = result.status  # type: ignore[assignment]
    section.confidence_score = result.confidence_score
    for claim in result.claims:
        claim_id = _add_claim(
            context,
            section.id,
            _strip_internal_source_tokens(claim.text),
            claim.claim_type,
            claim.source_ids,
            claim.confidence_score,
        )
        section.claim_ids.append(claim_id)
    _normalize_section_evidence_language(context, section)
    return result


class PlannerAgent(Agent):
    name = "Planner Agent"
    model = "gpt-5.5"
    reasoning_effort = "high"
    tools = ["structured_outputs"]

    async def run(self, context: AgentContext) -> AgentContext:
        objectives = []
        for section_id, title in REPORT_SECTION_ORDER:
            tag = "STRATEGY" if section_id in {"ai_strategy", "hcltech_penetration", "consensus"} else "RESEARCH"
            if section_id == "evidence_appendix":
                tag = "DELIVERABLE"
            objectives.append(ResearchObjective(tag=tag, text=f"Build {title}", section_id=section_id))
        context.report.sections = [
            ReportSection(
                id=section_id,
                title=title,
                summary="Pending source-backed research.",
                status="partial",
                confidence_score=0,
            )
            for section_id, title in REPORT_SECTION_ORDER
        ]
        context.report.quality_checks.append(
            QualityCheck(name="research_plan_created", passed=True, message=f"{len(objectives)} tagged objectives generated.")
        )
        return context


class SourceDiscoveryAgent(Agent):
    name = "Source Discovery Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "source_credibility_policy"]

    async def run(self, context: AgentContext) -> AgentContext:
        source = _system_source()
        context.report.sources.append(source)
        context.report.research_anchor.source_ids.append(source.id)
        context.report.research_anchor.raw_urls.append(source.url)
        provider = context.providers.search_provider()
        results = await provider.search(
            f"{context.run.company_name} latest annual report investor relations official filings"
        )
        for result in results[:10]:
            existing = _source_for_url(context, result.url)
            if existing:
                _enrich_source(existing)
                continue
            credibility = SourceCredibility.system if result.url.startswith("system://") else SourceCredibility.company_page
            discovered = _enrich_source(EvidenceSource(
                url=result.url,
                title=result.title,
                publisher=result.publisher,
                published_at=result.published_at,
                credibility=credibility,
                credibility_score=0.55 if credibility != SourceCredibility.system else 1,
            ))
            context.report.sources.append(discovered)
            context.report.research_anchor.source_ids.append(discovered.id)
            context.report.research_anchor.raw_urls.append(discovered.url)
        tier_counts: dict[str, int] = {}
        for report_source in context.report.sources:
            tier = report_source.source_tier or _infer_source_tier(report_source)
            tier_counts[tier.value] = tier_counts.get(tier.value, 0) + 1
        _replace_quality_check(
            context,
            QualityCheck(
                name="source_tier_policy",
                passed=True,
                message=(
                    "Source tiers active: exact financials require Tier 1; official press releases/newsroom support announced investments, partnerships, AI moves, and priorities; "
                    f"directional signals use Tier 3/4 with labels. Initial tier mix: {tier_counts}."
                ),
            ),
        )
        return context


class QuickSourceExpansionAgent(Agent):
    name = "Quick Source Expansion Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "quick_source_expansion", "press_release_discovery"]

    async def run(self, context: AgentContext) -> AgentContext:
        freshness = context.run.freshness_window.value
        company = context.run.company_name
        query_plan = [
            (
                f"{company} official investor relations annual report quarterly results earnings presentation latest",
                SourceCredibility.company_page,
                0.78,
                6,
            ),
            (
                f"{company} official press releases newsroom partnerships investments AI cloud customer wins last {freshness}",
                SourceCredibility.company_page,
                0.78,
                6,
            ),
            (
                f"{company} strategic partnership deal acquisition alliance contract announcement reputable news last {freshness}",
                SourceCredibility.reputable_news,
                0.74,
                6,
            ),
            (
                f"{company} AI strategy product launch automation cloud data platform roadmap official announcement last {freshness}",
                SourceCredibility.company_page,
                0.76,
                6,
            ),
            (
                f"{company} hiring jobs careers cloud AI data engineering cybersecurity locations last {freshness}",
                SourceCredibility.company_page,
                0.72,
                6,
            ),
            (
                f"{company} managed services outsourcing consulting transformation vendor partner modernization announcement",
                SourceCredibility.reputable_news,
                0.72,
                6,
            ),
        ]
        discovered = await _discover_many(context, query_plan)

        _replace_quality_check(
            context,
            QualityCheck(
                name="quick_source_expansion",
                passed=bool(discovered),
                severity="warning" if not discovered else "info",
                message=f"Quick Scan expanded source discovery across filings, press releases, partnerships, AI, hiring, and vendor signals with {len(_dedupe_preserve_order(discovered))} unique source references.",
            ),
        )
        return context


class DeepResearchPlanningAgent(Agent):
    name = "Deep Research Planning Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["research_anchor", "deep_outline"]

    async def run(self, context: AgentContext) -> AgentContext:
        context.report.quality_checks.append(
            QualityCheck(
                name="deep_research_plan_locked",
                passed=True,
                message="Deep run expanded beyond quick scan with source expansion, snapshots, critique, and evidence hardening stages.",
            )
        )
        return context


class OpenAIDeepResearchAgent(Agent):
    name = "OpenAI Deep Research Agent"
    model = "o3-deep-research"
    reasoning_effort = "background"
    tools = ["openai_deep_research", "web_search_preview", "background_polling"]

    async def run(self, context: AgentContext) -> AgentContext:
        prompt = f"""
Research {context.run.company_name} for a Draup-style account intelligence report from an HCLTech perspective.

Freshness window for news/signals/investments/partnerships/deals: {context.run.freshness_window.value}.

Required sections:
- Company overview and official financial snapshot.
- Exact revenue, R&D, geography, and segment trends from filings or investor materials only.
- Recent investments and capital allocation: capex, AI/cloud/data-center investments, facility expansion, acquisitions, strategic investments, and R&D shifts. Include exact amount, currency, geography, date/period, and source when available; mark unavailable when not exact.
- Partnerships, deals, and commercial moves: strategic partnerships, acquisitions, alliances, customer/deal announcements, cloud/AI/data partnerships, ecosystem moves, and contract signals. Distinguish announced partnerships from inferred opportunity.
- Account priorities by function.
- IT spend only when disclosed or defensible from exact public evidence.
- IT investment signals even when direct IT-spend numbers are not disclosed: hiring, cloud/AI investments, cost optimization, consultant/partner engagement, managed services, modernization, automation, vendor consolidation, and operating-model shifts. Label these as directional signals, not spend estimates.
- Technology stack signals backed by jobs, official pages, partner pages, or credible public evidence.
- Hiring and global footprint signals.
- Outsourcing/vendor/provider evidence.
- Key executives and buying-center map.
- AI strategy maturity and roadmap signals.
- HCLTech account-penetration implications, but label strategy as inference and cite premises.

Grounding rules:
- Prefer official filings, annual reports, investor presentations, earnings transcripts, official press releases/newsroom pages, reputable news, and official career/job pages.
- Treat official press releases as credible primary evidence for announced partnerships, investments, product launches, customer wins, roadmap statements, executive statements, and stated priorities.
- Do not invent financial amounts, vendor relationships, headcount, deal values, or executive names.
- Include inline citations and source metadata.
"""
        result = await context.providers.deep_research_provider().research(prompt)
        source_ids: list[str] = []
        for source_result in result.sources[:80]:
            source_id = _attach_extracted_page(
                context,
                url=source_result.url,
                title=source_result.title,
                publisher=source_result.publisher or "OpenAI Deep Research",
                credibility=SourceCredibility.reputable_news,
                credibility_score=0.82,
                text=source_result.snippet,
                metadata={},
            )
            source_ids.append(source_id)

        deep_source = _enrich_source(EvidenceSource(
            url=f"system://openai-deep-research/{result.response_id or context.run.id}",
            title=f"OpenAI Deep Research synthesis for {context.run.company_name}",
            publisher="OpenAI Deep Research",
            credibility=SourceCredibility.system,
            credibility_score=1.0,
        ))
        context.report.sources.append(deep_source)
        context.report.research_anchor.source_ids.append(deep_source.id)
        context.report.research_anchor.raw_urls.append(deep_source.url)
        if result.output_text:
            snapshot = SourceSnapshot(source_id=deep_source.id, text_excerpt=result.output_text[:40000], storage_uri=None)
            context.report.snapshots.append(snapshot)
            context.report.research_anchor.snapshot_ids.append(snapshot.id)
            deep_source.snapshot_id = snapshot.id

        context.report.quality_checks.append(
            QualityCheck(
                name="openai_deep_research_background",
                passed=result.status == "completed" and bool(result.output_text),
                severity="blocker" if context.run.mode == ResearchMode.deep and result.error else "info",
                message=(
                    f"OpenAI Deep Research status={result.status}, response_id={result.response_id}, "
                    f"tool_calls={result.tool_call_count}, sources={len(source_ids)}."
                    if not result.error
                    else f"OpenAI Deep Research failed: {result.error[:260]}"
                ),
            )
        )
        return context


class DeepSourceExpansionAgent(Agent):
    name = "Deep Source Expansion Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "source_expansion"]

    async def run(self, context: AgentContext) -> AgentContext:
        queries = [
            f"{context.run.company_name} annual report investor presentation official filing latest",
            f"{context.run.company_name} quarterly results earnings release investor presentation transcript latest revenue R&D capex",
            f"{context.run.company_name} official press releases newsroom partnerships investments AI cloud contracts latest",
            f"{context.run.company_name} recent investments capex acquisition expansion AI cloud data center official",
            f"{context.run.company_name} strategic partnership deal alliance acquisition customer contract AI cloud",
            f"{context.run.company_name} AI strategy partnerships product launch official announcement",
            f"{context.run.company_name} hiring jobs cloud AI data engineering locations",
            f"{context.run.company_name} outsourcing system integrator partner vendor relationship managed services consulting transformation",
            f"{context.run.company_name} cost optimization automation headcount investment consultants transformation program",
        ]
        discovered = await _discover_many(
            context,
            [(query, SourceCredibility.company_page, 0.68, 5) for query in queries],
        )
        context.report.quality_checks.append(
            QualityCheck(
                name="deep_source_expansion",
                passed=bool(discovered),
                severity="warning" if not discovered else "info",
                message=f"Expanded deep source set with {len(discovered)} additional source records.",
            )
        )
        return context


class FirecrawlEvidenceExtractionAgent(Agent):
    name = "Firecrawl Evidence Extraction Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "medium"
    tools = ["firecrawl", "source_snapshots"]

    async def run(self, context: AgentContext) -> AgentContext:
        firecrawl = context.providers.extraction_providers()[0]
        candidates = _prioritized_public_sources(context, context.providers.settings.firecrawl_max_sources_per_run)
        candidate_urls = [source.url for source in candidates[: context.providers.settings.firecrawl_max_sources_per_run]]
        result = await firecrawl.batch_extract_urls(candidate_urls)
        captured = 0
        for page in result.pages:
            if not page.text:
                continue
            _attach_extracted_page(
                context,
                url=page.url,
                title=page.title,
                publisher=page.metadata.get("publisher"),
                credibility=SourceCredibility.company_page,
                credibility_score=0.78,
                text=page.text,
                metadata=page.metadata,
            )
            captured += 1

        crawl_roots = [
            source.url
            for source in candidates
            if any(token in source.url.lower() for token in ["investors", "newsroom", "careers", "about"])
        ][:2]
        crawl_captured = 0
        for root_url in crawl_roots:
            crawl_result = await firecrawl.crawl_url(root_url, limit=6, max_depth=1)
            for page in crawl_result.pages:
                if not page.text:
                    continue
                _attach_extracted_page(
                    context,
                    url=page.url,
                    title=page.title,
                    publisher=page.metadata.get("publisher"),
                    credibility=SourceCredibility.company_page,
                    credibility_score=0.78,
                    text=page.text,
                    metadata=page.metadata,
                )
                crawl_captured += 1
        context.report.quality_checks.append(
            QualityCheck(
                name="firecrawl_extraction_jobs",
                passed=(captured + crawl_captured) >= 5,
                severity="blocker" if context.run.mode == ResearchMode.deep and (captured + crawl_captured) == 0 else "warning",
                message=(
                    f"Firecrawl batch status={result.status}, job_id={result.job_id}; "
                    f"captured {captured} batch pages and {crawl_captured} crawl pages."
                    + (f" Fallback/error: {result.error[:180]}" if result.error else "")
                ),
            )
        )
        return context


class ApifySignalExtractionAgent(Agent):
    name = "Apify Signal Extraction Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "medium"
    tools = ["apify", "job_signal_extraction"]

    async def run(self, context: AgentContext) -> AgentContext:
        apify = context.providers.extraction_providers()[1]
        candidate_urls = [
            source.url
            for source in _prioritized_public_sources(context, context.providers.settings.apify_max_crawl_pages)
            if source.url.startswith("http")
            and any(token in source.url.lower() for token in ["careers", "jobs", "locations", "technology", "newsroom", "partner"])
        ][: context.providers.settings.apify_max_crawl_pages]
        result = await apify.crawl_urls(candidate_urls)
        captured = 0
        for page in result.pages:
            if not page.text:
                continue
            credibility = SourceCredibility.job_or_career_page if any(token in page.url.lower() for token in ["careers", "jobs"]) else SourceCredibility.company_page
            _attach_extracted_page(
                context,
                url=page.url,
                title=page.title,
                publisher=page.metadata.get("publisher"),
                credibility=credibility,
                credibility_score=0.76,
                text=page.text,
                metadata=page.metadata,
            )
            captured += 1
        context.report.quality_checks.append(
            QualityCheck(
                name="apify_actor_extraction",
                passed=captured > 0,
                severity="warning" if result.status in {"skipped", "unavailable"} or captured == 0 else "info",
                message=f"Apify actor status={result.status}, run_id={result.job_id}; captured {captured} dataset pages."
                + (f" Error: {result.error[:180]}" if result.error else ""),
            )
        )
        return context


class GapCritiqueAgent(Agent):
    name = "Gap Critique Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["structured_outputs", "gap_critique"]

    async def run(self, context: AgentContext) -> AgentContext:
        await _synthesize_into_section(
            context,
            self,
            "evidence_appendix",
            (
                "Critique source coverage for a deep account intelligence report. "
                "Identify gaps for financials, technology stack, hiring, outsourcing, AI strategy, and account penetration. "
                "Do not introduce new facts."
            ),
        )
        return context


class RefinedSearchLoopAgent(Agent):
    name = "Refined Search Loop Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "query_refinement"]

    async def run(self, context: AgentContext) -> AgentContext:
        queries = [
            f"{context.run.company_name} technology stack jobs cloud data AI engineering public",
            f"{context.run.company_name} leadership CIO CTO CFO AI transformation",
            f"{context.run.company_name} recent strategic priorities earnings call transcript {context.run.freshness_window.value}",
            f"{context.run.company_name} official newsroom partnership investment product launch customer win",
            f"{context.run.company_name} quarterly results investor presentation capex R&D cost optimization",
            f"{context.run.company_name} managed services consulting transformation vendor partner announcement",
        ]
        discovered = await _discover_many(
            context,
            [(query, SourceCredibility.reputable_news, 0.7, 5) for query in queries],
        )
        context.report.quality_checks.append(
            QualityCheck(
                name="refined_search_loop",
                passed=bool(discovered),
                severity="warning" if not discovered else "info",
                message=f"Refined search loop added {len(discovered)} source records.",
            )
        )
        return context


class EvidenceHardeningAgent(Agent):
    name = "Evidence Hardening Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["claim_evidence_map", "source_quality"]

    async def run(self, context: AgentContext) -> AgentContext:
        live_sources = [source for source in context.report.sources if source.url.startswith("http")]
        snapshots = [snapshot for snapshot in context.report.snapshots if snapshot.text_excerpt and len(snapshot.text_excerpt) >= 300]
        passed = len(live_sources) >= 20 and len(snapshots) >= 10
        context.report.quality_checks.append(
            QualityCheck(
                name="deep_evidence_hardening",
                passed=passed,
                severity="blocker" if context.run.mode == ResearchMode.deep and not passed else "info",
                message=f"Deep evidence set has {len(live_sources)} live sources and {len(snapshots)} extracted snapshots before synthesis.",
            )
        )
        return context


class CompanyOverviewAgent(Agent):
    name = "Company Overview Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "structured_outputs"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered_ids = await _discover(
            context,
            f"{context.run.company_name} official company overview headquarters employees revenue latest annual report",
            SourceCredibility.company_page,
            score=0.7,
            limit=6,
        )
        source_ids = _merge_source_ids(
            discovered_ids,
            _keyword_source_ids(context, ["about", "overview", "annual report", "10-k", "investor", "company", "quarterly", "results"], limit=14),
            _preferred_source_ids(context, 8),
            limit=18,
        )
        await _extract_sources(context, source_ids, limit=8)
        claim_id = _add_claim(
            context,
            "company_overview",
            f"{context.run.company_name} overview must be built from official company, investor, or filing sources.",
            "fact" if discovered_ids else "recommendation",
            source_ids,
            0.75 if discovered_ids else 0.9,
        )
        section = _section(context, "company_overview")
        section.summary = (
            "Company overview is partial until official company, investor, or filing evidence is extracted into exact facts."
        )
        section.content = {
            "company_name": context.run.company_name,
            "source_policy": "Official company, investor, filing, and credible public sources only.",
            "discovered_source_ids": source_ids,
        }
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.75 if discovered_ids else 0.85
        await _synthesize_into_section(
            context,
            self,
            "company_overview",
            (
                "Build a concise company overview from extracted evidence. Include business description, headquarters, major segments, "
                "strategic posture, recent scale indicators, and report limitations. Use exact values only when present in evidence. "
                "Do not say the overview is merely configured."
            ),
            source_ids,
        )
        return context


class FinancialAgent(Agent):
    name = "Financial Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["firecrawl", "official_filings", "exact_value_policy"]

    async def run(self, context: AgentContext) -> AgentContext:
        source_ids = _merge_source_ids(
            _keyword_source_ids(context, ["10-k", "annual", "financial", "revenue", "segment", "investor", "sec.gov", "results", "quarter", "earnings", "presentation", "r&d", "capex"], limit=20),
            _preferred_source_ids(context, 8),
            limit=24,
        )
        await _extract_sources(context, source_ids, limit=12)
        claim_id = _add_claim(
            context,
            "financial_trends",
            "Exact financial metrics must be extracted from official annual reports, quarterly results, investor presentations, earnings releases, transcripts, or regulatory filings; unavailable applies only to a metric that is not present in the extracted evidence.",
            "recommendation",
            source_ids,
            1.0,
        )
        context.report.extracted_values.extend(
            [
                ExtractedValue(
                    label="Revenue",
                    value=None,
                    unit="reported currency",
                    exact=True,
                    unavailable_reason="Exact revenue value not found in the extracted official financial evidence for this run.",
                ),
                ExtractedValue(
                    label="R&D Spend",
                    value=None,
                    unit="reported currency",
                    exact=True,
                    unavailable_reason="Exact R&D value not found in the extracted official financial evidence for this run.",
                ),
            ]
        )
        section = _section(context, "financial_trends")
        section.summary = "Financial metrics are exact-only, but annual reports, quarterly results, investor releases, earnings materials, and filings are all valid financial sources."
        section.content = {"policy": "No approximate financials; exact source-backed values only."}
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.72
        await _synthesize_into_section(
            context,
            self,
            "financial_trends",
            (
                "Extract exact financial facts from official filings, annual reports, quarterly reports, investor releases, earnings presentations, or earnings materials in evidence. "
                "Look for revenue, segment revenue, geography, R&D, capex, free cash flow, growth rates, and reporting period. "
                "If exact values are not present in the evidence excerpts, use 'Exact value not disclosed in extracted evidence' for that attribute. Do not estimate."
            ),
            source_ids,
        )
        it_section = _section(context, "it_spend")
        it_claim_id = _add_claim(
            context,
            "it_spend",
            "Direct IT spend is not estimated, but IT investment signals can be synthesized from public evidence such as hiring, AI/cloud investments, modernization programs, cost optimization, partner/consulting activity, and managed services.",
            "recommendation",
            source_ids,
            1.0,
        )
        it_section.summary = "Direct IT spend numeric output is exact-only; directional IT investment signals are synthesized when supported by public evidence."
        it_section.content = {"policy": "No benchmark-only spend estimates; use cited directional investment signals when exact spend is not disclosed."}
        it_section.claim_ids.append(it_claim_id)
        it_section.status = "partial"
        it_section.confidence_score = 0.68
        return context


class RecentInvestmentsAgent(Agent):
    name = "Recent Investments Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["openai_web_search", "firecrawl", "exact_value_policy", "structured_outputs"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered: list[str] = []
        queries = [
            f"{context.run.company_name} recent investments capex capital expenditure acquisition expansion AI cloud data center official {context.run.freshness_window.value}",
            f"{context.run.company_name} investor presentation capital allocation investments acquisition R&D spend latest",
            f"{context.run.company_name} investment commitment partnership expansion facility deal amount announced",
        ]
        discovered.extend(
            await _discover_many(
                context,
                [(query, SourceCredibility.reputable_news, 0.78, 6) for query in queries],
            )
        )
        source_ids = _merge_source_ids(
            discovered,
            _keyword_source_ids(context, ["investment", "capex", "capital", "acquisition", "merge", "spend", "manufacturing", "r&d", "facility", "expansion", "buyback"], limit=22),
            _preferred_source_ids(context, 8),
            limit=30,
        )
        await _extract_sources(context, source_ids, limit=14)
        claim_id = _add_claim(
            context,
            "recent_investments",
            "Recent investment details require exact public evidence for amount, currency, timing, geography, investment type, and business rationale; missing fields are marked unavailable.",
            "recommendation",
            source_ids,
            0.96,
        )
        section = _section(context, "recent_investments")
        section.summary = "Recent investments are analyzed only when exact public evidence supports the investment type, amount, timing, geography, and rationale."
        section.content = {
            "investment_types": [
                "capex",
                "AI/cloud/data-center investment",
                "facility expansion",
                "acquisition",
                "strategic investment",
                "R&D shift",
                "partnership-linked investment",
            ],
            "exact_value_policy": "No approximate investment amounts.",
        }
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.8
        await _synthesize_into_section(
            context,
            self,
            "recent_investments",
            (
                "Extract recent investment and capital allocation details from evidence only. "
                "For each supported item, identify investment type, amount, currency, date or period, geography, business rationale, and source. "
                "If the source states a symbol such as $ or USD, preserve the exact currency. If amount or other numeric attributes are not exact, say 'Exact value not disclosed' rather than estimating. "
                "Still capture a Directional signal when credible evidence confirms investment activity, capital allocation focus, facility expansion, AI/cloud spend intent, acquisition activity, or R&D shift. "
                "Separate company investment facts from strategic implications."
            ),
            source_ids,
        )
        section = _section(context, "recent_investments")
        if section.status == "unavailable" or section.confidence_score < 0.70:
            _fallback_section_from_claims(
                context,
                "recent_investments",
                prefix="Supported investment and deal evidence includes",
                max_claims=5,
                min_confidence=0.72,
                caveat="Exact amounts, terms, geography, or execution periods remain unavailable when they are not stated in the cited records.",
            )
        return context


class PartnershipsDealsAgent(Agent):
    name = "Partnerships/Deals Agent"
    model = "gpt-5.5"
    reasoning_effort = "high"
    tools = ["openai_web_search", "structured_outputs", "deal_signal_policy"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered: list[str] = []
        queries = [
            f"{context.run.company_name} strategic partnership deal alliance acquisition customer contract announcement AI cloud data latest",
            f"{context.run.company_name} partnership collaboration agreement investment commercial deal press release",
            f"{context.run.company_name} major customer deal transformation contract partnership {context.run.freshness_window.value}",
        ]
        discovered.extend(
            await _discover_many(
                context,
                [(query, SourceCredibility.reputable_news, 0.78, 6) for query in queries],
            )
        )
        source_ids = _merge_source_ids(
            discovered,
            _keyword_source_ids(context, ["partnership", "collaboration", "deal", "acquisition", "alliance", "customer", "contract", "selects", "mou", "managed services"], limit=24),
            _preferred_source_ids(context, 8),
            limit=32,
        )
        await _extract_sources(context, source_ids, limit=14)
        claim_id = _add_claim(
            context,
            "partnerships_deals",
            "Partnerships, deals, and commercial moves are listed only when backed by official announcements, filings, credible news, or public customer/partner evidence.",
            "recommendation",
            source_ids,
            0.95,
        )
        section = _section(context, "partnerships_deals")
        section.summary = "Partnerships, deals, and commercial moves are classified from public evidence and separated from inferred opportunity themes."
        section.content = {
            "deal_types": [
                "strategic partnership",
                "technology alliance",
                "customer deal",
                "acquisition",
                "joint solution",
                "ecosystem move",
            ],
            "unsupported_policy": "Do not infer deal value or commercial scale without exact evidence.",
        }
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.8
        await _synthesize_into_section(
            context,
            self,
            "partnerships_deals",
            (
                "Summarize recent partnerships, deals, acquisitions, alliances, and commercial moves from evidence only. "
                "Include parties, date/period, deal type, stated objective, investment or deal value only if exact, and strategic implication. "
                "Do not infer contract value, partnership depth, or customer traction unless the source states it. "
                "When value or scale is missing, use 'Exact value not disclosed' while still preserving the Directional signal and strategic implication."
            ),
            source_ids,
        )
        return context


class AccountPrioritiesAgent(Agent):
    name = "Account Priorities Agent"
    model = "gpt-5.5"
    reasoning_effort = "high"
    tools = ["openai_web_search", "structured_outputs"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered_ids = await _discover(
            context,
            f"{context.run.company_name} earnings call strategic priorities finance sales marketing IT HR customer support AI cloud",
            SourceCredibility.earnings_transcript,
            score=0.78,
            limit=6,
        )
        source_ids = discovered_ids or _preferred_source_ids(context)
        source_ids = _merge_source_ids(
            discovered_ids,
            _keyword_source_ids(context, ["earnings", "transcript", "results", "annual", "10-k", "strategy", "priorities", "press", "newsroom", "investor", "cost", "growth"], limit=22),
            _preferred_source_ids(context, 8),
            limit=30,
        )
        await _extract_sources(context, source_ids, limit=12)
        functions = [
            "Finance",
            "Sales & Marketing",
            "Customer Support",
            "IT",
            "HR",
            "Supply Chain/Operations",
            "ER&D/R&D",
            "Management & Strategy",
        ]
        claim_id = _add_claim(
            context,
            "account_priorities",
            "Account-priority pages require section-specific evidence from filings, earnings calls, press releases, and credible news.",
            "recommendation",
            source_ids,
            1.0,
        )
        section = _section(context, "account_priorities")
        section.summary = (
            "Account priorities are reported only when section-specific filings, earnings calls, press releases, or credible news support them."
        )
        section.content = {"business_functions": functions, "required_evidence": ["filings", "earnings calls", "press releases", "credible news"]}
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.8
        await _synthesize_into_section(
            context,
            self,
            "account_priorities",
            (
                "Synthesize account priorities by business function from the provided evidence. "
                "Return only source-backed priorities, use cases, workloads, and expected outcomes. "
                "If exact attributes are thin, say what exact value is not disclosed, but still synthesize Directional signals when credible evidence supports them."
            ),
            source_ids,
        )
        return context


class TechnologyStackAgent(Agent):
    name = "Tech Stack Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["apify", "firecrawl", "structured_outputs"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered_ids = await _discover(
            context,
            f"{context.run.company_name} technology stack cloud ERP database cybersecurity data platform jobs partner official",
            SourceCredibility.job_or_career_page,
            score=0.7,
            limit=6,
        )
        source_ids = discovered_ids or _preferred_source_ids(context)
        source_ids = _merge_source_ids(
            discovered_ids,
            _keyword_source_ids(context, ["technology", "cloud", "database", "sap", "security", "platform", "careers", "jobs", "ai", "data", "analytics", "devops", "erp"], limit=22),
            _preferred_source_ids(context, 8),
            limit=30,
        )
        await _extract_sources(context, source_ids, limit=12)
        categories = [
            "Analytics & BI",
            "AI/ML",
            "Big Data",
            "Cloud",
            "Database",
            "DevOps",
            "ERP",
            "Finance",
            "HCM",
            "Security",
        ]
        claim_id = _add_claim(
            context,
            "technology_stack",
            "Technology stack entries must be backed by job postings, official pages, partner pages, or credible public signals.",
            "recommendation",
            source_ids,
            0.95,
        )
        section = _section(context, "technology_stack")
        section.summary = (
            "Technology stack analysis is partial; no vendor, platform, or tool will be listed without public job, official, partner, or credible evidence."
        )
        section.content = {"categories": categories, "tools": []}
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.85
        await _synthesize_into_section(
            context,
            self,
            "technology_stack",
            (
                "Identify technology stack signals only from public evidence. "
                "Name vendors, platforms, categories, and confidence only when the evidence supports them. "
                "Use 'Directional signal' for job, partner, customer, or ecosystem evidence that indicates usage without proving enterprise-wide adoption."
            ),
            source_ids,
        )
        return context


class HiringFootprintAgent(Agent):
    name = "Hiring/Footprint Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["apify", "firecrawl"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered_ids = await _discover(
            context,
            f"{context.run.company_name} careers jobs hiring locations cloud AI data engineering",
            SourceCredibility.job_or_career_page,
            score=0.72,
            limit=6,
        )
        source_ids = discovered_ids or _preferred_source_ids(context)
        source_ids = _merge_source_ids(
            discovered_ids,
            _keyword_source_ids(context, ["careers", "jobs", "locations", "software", "data", "analytics", "engineering", "cloud", "ai", "security", "digital"], limit=22),
            _preferred_source_ids(context, 8),
            limit=30,
        )
        await _extract_sources(context, source_ids, limit=12)
        claim_id = _add_claim(
            context,
            "footprint_hiring",
            "Hiring and footprint analysis requires exact public job, career, or official location evidence; counts and trends are not inferred.",
            "recommendation",
            source_ids,
            0.95,
        )
        section = _section(context, "footprint_hiring")
        section.summary = (
            "Hiring and footprint analysis is partial unless public job, career, or official location evidence provides exact role, skill, and location signals."
        )
        section.content = {"freshness_window": context.run.freshness_window.value, "locations": [], "skills": []}
        section.claim_ids.append(claim_id)
        section.status = "partial" if discovered_ids else "unavailable"
        section.confidence_score = 0.72 if discovered_ids else 1
        await _synthesize_into_section(
            context,
            self,
            "footprint_hiring",
            (
                "Summarize hiring, footprint, location, role, and skill signals from the supplied evidence only. "
                "Do not estimate headcount or hiring volume. Use 'Directional signal' for roles, skills, and locations visible in public evidence; use 'Exact value not disclosed' for missing counts."
            ),
            source_ids,
        )
        return context


class NewsSignalsAgent(Agent):
    name = "News/Signals Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "news_credibility_policy"]

    async def run(self, context: AgentContext) -> AgentContext:
        signal_source_ids = (await _discover(
            context,
            f"{context.run.company_name} recent news strategy partnerships product launch AI cloud {context.run.freshness_window.value}",
            SourceCredibility.reputable_news,
            score=0.74,
            limit=6,
        ))
        signal_source_ids = _merge_source_ids(
            signal_source_ids,
            _keyword_source_ids(context, ["newsroom", "press", "announces", "results", "partnership", "collaboration", "ai", "investment", "customer", "contract", "launch"], limit=24),
            _preferred_source_ids(context, 8),
            limit=32,
        )
        await _extract_sources(context, signal_source_ids, limit=12)
        claim_id = _add_claim(
            context,
            "key_signals",
            "Key signals must come from official announcements or reputable news within the selected freshness window.",
            "recommendation",
            signal_source_ids,
            0.95,
        )
        section = _section(context, "key_signals")
        section.summary = "Signal validation policy is configured."
        section.content = {"freshness_window": context.run.freshness_window.value, "signals": []}
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.9
        await _synthesize_into_section(
            context,
            self,
            "key_signals",
            (
                "Classify recent strategic signals from the evidence. Use only credible news or official sources. "
                "Do not restate a signal unless the source supports it."
            ),
            signal_source_ids,
        )
        return context


class ITSpendSignalsAgent(Agent):
    name = "IT Spend Signals Agent"
    model = "gpt-5.5"
    reasoning_effort = "high"
    tools = ["cross_section_claims", "investment_signal_policy"]

    async def run(self, context: AgentContext) -> AgentContext:
        source_ids = _merge_source_ids(
            _source_ids_from_claims(
                context,
                section_ids={"financial_trends", "recent_investments", "partnerships_deals", "account_priorities", "technology_stack", "footprint_hiring", "key_signals"},
                keywords=[
                    "cloud",
                    "ai",
                    "automation",
                    "modernization",
                    "managed services",
                    "cost",
                    "hiring",
                    "engineering",
                    "data",
                    "capex",
                    "investment",
                    "software",
                    "security",
                    "outsourcing",
                    "consulting",
                ],
                limit=22,
            ),
            _source_ids_from_signals(
                context,
                signal_types={
                    EvidenceSignalType.investment,
                    EvidenceSignalType.partnership_deal,
                    EvidenceSignalType.technology_stack,
                    EvidenceSignalType.hiring_footprint,
                    EvidenceSignalType.news_signal,
                },
                keywords=["cloud", "ai", "automation", "modernization", "managed", "cost", "hiring", "data", "software", "security", "investment"],
                limit=18,
            ),
            _keyword_source_ids(context, ["results", "investor", "cloud", "ai", "automation", "managed", "careers", "jobs", "cost", "consulting"], limit=12),
            _preferred_source_ids(context, 6),
            limit=24,
        )
        await _synthesize_into_section(
            context,
            self,
            "it_spend",
            (
                "Create an IT Spend and Investment Signals section. Do not estimate a numeric IT spend unless an exact figure is cited. "
                "Instead synthesize directional signals from the report evidence: AI/cloud investment, modernization programs, managed services, "
                "cost optimization, vendor/partner activity, hiring and skills demand, automation/security priorities, and operating-model shifts. "
                "Label each as a Directional IT investment signal and cite source IDs. Do not call the section unavailable when the exact spend number is missing but other evidence signals exist."
            ),
            source_ids,
        )
        section = _section(context, "it_spend")
        if section.status == "unavailable" or section.confidence_score < 0.58 or len(section.claim_ids) <= 1:
            _fallback_section_from_related_claims(
                context,
                "it_spend",
                source_section_ids={"financial_trends", "recent_investments", "partnerships_deals", "account_priorities", "technology_stack", "footprint_hiring", "key_signals"},
                keywords=["cloud", "ai", "automation", "modernization", "managed", "cost", "hiring", "engineering", "data", "software", "security", "investment"],
                summary_prefix="Directional IT investment signals include",
                claim_prefix="IT investment signal",
                claim_type="inference",
                max_claims=6,
                min_confidence=0.68,
                caveat="No numeric IT-spend estimate is produced unless an exact disclosed spend figure is found.",
            )
        return context


class OutsourcingVendorAgent(Agent):
    name = "Outsourcing/Vendor Agent"
    model = "gpt-5.5"
    reasoning_effort = "high"
    tools = ["openai_web_search", "apify", "no_estimated_share_policy"]

    async def run(self, context: AgentContext) -> AgentContext:
        discovered: list[str] = []
        queries = [
            f"{context.run.company_name} managed services outsourcing partner system integrator consulting transformation vendor press release",
            f"{context.run.company_name} selects partner managed services cloud transformation modernization contract announcement",
            f"{context.run.company_name} Accenture Deloitte IBM Infosys TCS Wipro HCLTech Capgemini Cognizant partnership consulting",
        ]
        discovered.extend(
            await _discover_many(
                context,
                [(query, SourceCredibility.reputable_news, 0.74, 6) for query in queries],
            )
        )
        source_ids = _merge_source_ids(
            discovered,
            _source_ids_from_claims(
                context,
                section_ids={"partnerships_deals", "technology_stack", "account_priorities", "key_signals", "footprint_hiring"},
                keywords=["managed services", "partner", "vendor", "outsourcing", "consulting", "cloud", "transformation", "modernization", "selects"],
                limit=40,
            ),
            _keyword_source_ids(context, ["managed", "outsourcing", "partner", "vendor", "consulting", "transformation", "modernization", "selects", "contract", "services"], limit=24),
            _preferred_source_ids(context, 8),
            limit=34,
        )
        await _extract_sources(context, source_ids, limit=12)
        claim_id = _add_claim(
            context,
            "outsourcing_vendor",
            "Provider relationships can be listed only when backed by public partner, announcement, job, or credible relationship evidence.",
            "recommendation",
            source_ids,
            0.95,
        )
        section = _section(context, "outsourcing_vendor")
        section.summary = "Vendor analysis separates direct outsourcing evidence from broader partner, consulting, managed-services, and transformation signals."
        section.content = {"providers": [], "numeric_policy": "No estimated shares or outsourcing workforce counts."}
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.72
        await _synthesize_into_section(
            context,
            self,
            "outsourcing_vendor",
            (
                "Build an outsourcing/vendor/provider signal view from credible public evidence. "
                "Directly list outsourcing or managed-services providers only when supported. "
                "Also capture adjacent partner, consulting, transformation, managed-services, vendor-consolidation, and cost-optimization signals. "
                "Do not estimate vendor market share, outsourced headcount, spend, or contract value without exact evidence."
            ),
            source_ids,
        )
        if section.status == "unavailable" or section.confidence_score < 0.58 or len(section.claim_ids) <= 1:
            _fallback_section_from_related_claims(
                context,
                "outsourcing_vendor",
                source_section_ids={"partnerships_deals", "technology_stack", "account_priorities", "key_signals", "footprint_hiring"},
                keywords=["managed services", "partner", "vendor", "outsourcing", "consulting", "cloud", "transformation", "modernization", "selects"],
                summary_prefix="Public sourcing and provider signals include",
                claim_prefix="Provider signal",
                claim_type="inference",
                max_claims=6,
                min_confidence=0.68,
                caveat="No provider share, spend, or outsourced-headcount estimate is produced without exact disclosure.",
            )
        return context


class ExecutiveAgent(Agent):
    name = "Executive Agent"
    model = "gpt-5.4-mini"
    reasoning_effort = "high"
    tools = ["openai_web_search", "buying_center_map"]

    async def run(self, context: AgentContext) -> AgentContext:
        executive_source_ids = (await _discover(
            context,
            f"{context.run.company_name} executive leadership CIO CTO CFO CHRO business unit leaders",
            SourceCredibility.company_page,
            score=0.72,
            limit=6,
        ))
        executive_source_ids = _merge_source_ids(
            executive_source_ids,
            _keyword_source_ids(context, ["leadership", "executive", "governance", "board", "ceo", "cfo", "cto", "cio", "chief", "management"], limit=22),
            _preferred_source_ids(context, 8),
            limit=30,
        )
        await _extract_sources(context, executive_source_ids, limit=12)
        claim_id = _add_claim(
            context,
            "executives",
            "The buying-center map is generated from verified executive, functional leader, and strategic initiative evidence.",
            "recommendation",
            executive_source_ids,
            0.9,
        )
        section = _section(context, "executives")
        section.summary = (
            "The buying-center map is partial until verified executive and functional-leader evidence is available for named stakeholders."
        )
        section.content = {
            "buying_centers": [
                "CIO/CTO",
                "CFO/Finance Transformation",
                "CHRO/Workforce",
                "Business Unit Leaders",
                "Procurement/Vendor Management",
            ],
            "executives": [],
        }
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.85
        await _synthesize_into_section(
            context,
            self,
            "executives",
            (
                "Build a buying-center map from verified executive and leadership evidence. "
                "Name executives only when evidence supports the name and role. "
                "Otherwise identify the buying center as a target persona without inventing a person."
            ),
            executive_source_ids,
        )
        return context


class AIStrategyAgent(Agent):
    name = "AI Strategy Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["openai_web_search", "structured_outputs"]

    async def run(self, context: AgentContext) -> AgentContext:
        ai_source_ids = (await _discover(
            context,
            f"{context.run.company_name} AI strategy artificial intelligence investments partnerships product roadmap",
            SourceCredibility.reputable_news,
            score=0.76,
            limit=6,
        ))
        ai_source_ids = _merge_source_ids(
            ai_source_ids,
            _source_ids_from_claims(
                context,
                section_ids={"recent_investments", "partnerships_deals", "account_priorities", "technology_stack", "footprint_hiring", "key_signals"},
                keywords=["ai", "artificial", "automation", "cloud", "ran", "6g", "software", "data", "analytics", "radio", "network", "private 5g"],
                limit=30,
            ),
            _source_ids_from_signals(
                context,
                signal_types={
                    EvidenceSignalType.investment,
                    EvidenceSignalType.partnership_deal,
                    EvidenceSignalType.technology_stack,
                    EvidenceSignalType.hiring_footprint,
                    EvidenceSignalType.news_signal,
                },
                keywords=["ai", "artificial", "automation", "cloud", "data", "analytics", "software", "roadmap", "product", "platform"],
                limit=24,
            ),
            _keyword_source_ids(
                context,
                ["ai", "artificial", "nvidia", "oracle", "arm", "watson", "watsonx", "automation", "enterprise ai", "hybrid cloud", "ran", "6g", "private 5g"],
                limit=28,
            ),
            _preferred_source_ids(context, 8),
            limit=42,
        )
        await _extract_sources(context, ai_source_ids, limit=14)
        claim_id = _add_claim(
            context,
            "ai_strategy",
            "AI strategy assessment must distinguish cited company facts from HCLTech-facing strategic inference.",
            "recommendation",
            ai_source_ids,
            0.95,
        )
        section = _section(context, "ai_strategy")
        section.summary = "AI strategy assessment is pending verified evidence on AI investments, partnerships, offerings, adoption, and roadmap signals."
        section.content = {
            "dimensions": ["maturity", "investments", "partnerships", "products", "talent", "risks", "roadmap"],
            "assessment": [],
        }
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.85
        await _synthesize_into_section(
            context,
            self,
            "ai_strategy",
            (
                "Assess AI maturity, AI investments, partnerships, product direction, talent signals, risks, and likely roadmap. "
                "Official press releases are acceptable primary evidence for AI product launches, partnerships, roadmap statements, and executive-stated priorities. "
                "Separate facts from strategic inferences. Cite source IDs for every claim."
            ),
            ai_source_ids,
        )
        section = _section(context, "ai_strategy")
        if section.status == "unavailable" or section.confidence_score < 0.65 or len(section.claim_ids) <= 1:
            _fallback_section_from_related_claims(
                context,
                "ai_strategy",
                source_section_ids={"recent_investments", "partnerships_deals", "account_priorities", "technology_stack", "footprint_hiring", "key_signals"},
                keywords=["ai", "artificial", "automation", "cloud", "ran", "6g", "software", "data", "analytics", "radio", "network", "private 5g"],
                summary_prefix="AI strategy signals indicate",
                claim_prefix="AI strategy signal",
                claim_type="inference",
                max_claims=7,
                min_confidence=0.72,
                caveat="This is a strategy assessment from cited public signals, not a claim of undisclosed internal roadmap.",
            )
        return context


class HCLTechPenetrationAgent(Agent):
    name = "HCLTech Penetration Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["verified_claims", "strategy_synthesis"]

    async def run(self, context: AgentContext) -> AgentContext:
        source_ids = _merge_source_ids(
            _source_ids_from_claims(
                context,
                section_ids={
                    "company_overview",
                    "financial_trends",
                    "recent_investments",
                    "partnerships_deals",
                    "account_priorities",
                    "it_spend",
                    "technology_stack",
                    "footprint_hiring",
                    "key_signals",
                    "outsourcing_vendor",
                    "executives",
                    "ai_strategy",
                },
                keywords=[
                    "ai",
                    "cloud",
                    "automation",
                    "modernization",
                    "managed",
                    "partner",
                    "investment",
                    "growth",
                    "cost",
                    "security",
                    "data",
                    "software",
                    "hiring",
                    "regional",
                    "customer",
                    "enterprise",
                ],
                limit=28,
            ),
            _source_ids_from_signals(
                context,
                signal_types={
                    EvidenceSignalType.investment,
                    EvidenceSignalType.partnership_deal,
                    EvidenceSignalType.strategic_priority,
                    EvidenceSignalType.it_investment,
                    EvidenceSignalType.technology_stack,
                    EvidenceSignalType.hiring_footprint,
                    EvidenceSignalType.news_signal,
                    EvidenceSignalType.vendor_outsourcing,
                    EvidenceSignalType.executive_buying_center,
                    EvidenceSignalType.ai_strategy,
                },
                keywords=[
                    "ai",
                    "cloud",
                    "automation",
                    "modernization",
                    "managed",
                    "partner",
                    "investment",
                    "growth",
                    "cost",
                    "security",
                    "data",
                    "software",
                    "hiring",
                    "enterprise",
                ],
                limit=36,
            ),
            _keyword_source_ids(
                context,
                ["ai", "cloud", "partnership", "investment", "annual", "10-k", "executive", "careers", "technology", "outsourcing", "security", "modernization"],
                limit=28,
            ),
            _preferred_source_ids(context, 10),
            limit=50,
        )
        claim_id = _add_claim(
            context,
            "hcltech_penetration",
            "HCLTech account penetration guidance should recommend what to build or do, without force-fitting current capability mappings.",
            "recommendation",
            source_ids,
            0.95,
        )
        section = _section(context, "hcltech_penetration")
        section.summary = "HCLTech account-penetration guidance is pending verified account priorities, technology, sourcing, executive, and AI-strategy evidence."
        section.content = {
            "entry_points": ["AI transformation", "data modernization", "cloud operations", "industry process modernization"],
            "first_90_days": [
                "Validate executive buying centers against public evidence.",
                "Prioritize one AI-led custom solution theme with measurable business outcome.",
                "Build a pursuit brief from verified account priorities and open whitespace.",
            ],
        }
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.9
        await _synthesize_into_section(
            context,
            self,
            "hcltech_penetration",
            (
                "Create HCLTech account-penetration guidance from verified evidence. "
                "Recommend what HCLTech should build or do, entry points, custom solution themes, first-90-day pursuit motions, risks, and triggers. "
                "You may recommend custom HCLTech solution themes as strategic inferences from cited account premises. "
                "Use the evidence graph signals attached to sources to connect investments, partnerships, hiring, technology, AI, vendor, and executive evidence into account entry plays. "
                "Do not claim a current HCLTech capability inventory unless it is in evidence; focus on what HCLTech should build, test, or propose."
            ),
            source_ids,
        )
        section = _section(context, "hcltech_penetration")
        if section.status == "unavailable" or section.confidence_score < 0.62 or len(section.claim_ids) <= 1:
            _fallback_section_from_related_claims(
                context,
                "hcltech_penetration",
                source_section_ids={
                    "recent_investments",
                    "partnerships_deals",
                    "account_priorities",
                    "it_spend",
                    "technology_stack",
                    "footprint_hiring",
                    "key_signals",
                    "outsourcing_vendor",
                    "executives",
                    "ai_strategy",
                },
                keywords=["ai", "cloud", "automation", "modernization", "managed", "partner", "investment", "growth", "cost", "security", "data", "software", "hiring", "enterprise"],
                summary_prefix="HCLTech should pursue evidence-led plays around",
                claim_prefix="HCLTech penetration premise",
                claim_type="recommendation",
                max_claims=8,
                min_confidence=0.70,
                caveat="These are account-penetration recommendations derived from cited public signals and should be validated with account teams before client use.",
            )
        _apply_hcl_strategy_playbook(context, source_ids)
        return context


class ConsensusAgent(Agent):
    name = "Consensus Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["verified_claims", "strategy_synthesis"]

    async def run(self, context: AgentContext) -> AgentContext:
        source_ids = _merge_source_ids(
            _source_ids_from_claims(
                context,
                section_ids={
                    "company_overview",
                    "financial_trends",
                    "recent_investments",
                    "partnerships_deals",
                    "account_priorities",
                    "it_spend",
                    "technology_stack",
                    "footprint_hiring",
                    "key_signals",
                    "outsourcing_vendor",
                    "executives",
                    "ai_strategy",
                    "hcltech_penetration",
                },
                limit=45,
            ),
            _source_ids_from_signals(
                context,
                signal_types={
                    EvidenceSignalType.investment,
                    EvidenceSignalType.partnership_deal,
                    EvidenceSignalType.strategic_priority,
                    EvidenceSignalType.it_investment,
                    EvidenceSignalType.technology_stack,
                    EvidenceSignalType.hiring_footprint,
                    EvidenceSignalType.news_signal,
                    EvidenceSignalType.vendor_outsourcing,
                    EvidenceSignalType.executive_buying_center,
                    EvidenceSignalType.ai_strategy,
                    EvidenceSignalType.hcltech_opportunity,
                },
                limit=45,
            ),
            _preferred_source_ids(context, 12),
            limit=50,
        )
        claim_id = _add_claim(
            context,
            "consensus",
            "Consensus recommendations are generated only from verified claims and explicitly labeled strategic inferences.",
            "recommendation",
            source_ids,
            0.95,
        )
        section = _section(context, "consensus")
        section.summary = "Consensus recommendation is pending verified section-level evidence and should not overstate unsupported account moves."
        section.content = {"top_moves": ["Run live deep research to populate evidence-backed account moves."]}
        section.claim_ids.append(claim_id)
        section.status = "partial"
        section.confidence_score = 0.9
        await _synthesize_into_section(
            context,
            self,
            "consensus",
            (
                "Produce a concise consensus recommendation from the report claims and evidence. "
                "Rank top account moves, confidence, rationale, and risks. "
                "Use recommendations when their premises are cited; do not require the recommendation itself to be stated verbatim by a source. "
                "Use the cross-section evidence graph signals to reason across finance, investments, partnerships, hiring, technology, AI, vendor, executive, and news evidence. "
                "Do not leave consensus unavailable when multiple partial sections have cited claims or evidence signals."
            ),
            source_ids,
        )
        section = _section(context, "consensus")
        if section.status == "unavailable" or section.confidence_score < 0.62 or len(section.claim_ids) <= 1:
            _fallback_section_from_related_claims(
                context,
                "consensus",
                source_section_ids={
                    "recent_investments",
                    "partnerships_deals",
                    "account_priorities",
                    "it_spend",
                    "technology_stack",
                    "footprint_hiring",
                    "key_signals",
                    "outsourcing_vendor",
                    "executives",
                    "ai_strategy",
                    "hcltech_penetration",
                },
                keywords=["ai", "cloud", "automation", "modernization", "managed", "partner", "investment", "growth", "cost", "security", "data", "software", "hiring", "enterprise", "regional"],
                summary_prefix="Consensus recommendation",
                claim_prefix="Consensus premise",
                claim_type="recommendation",
                max_claims=8,
                min_confidence=0.74,
                caveat="The recommendation is a synthesis of cited public evidence, not a substitute for account-team validation.",
            )
        refresh_evidence_tables(context)
        evidence_section = _section(context, "evidence_appendix")
        source_tier_mix: dict[str, int] = {}
        for source in context.report.sources:
            tier = source.source_tier or _infer_source_tier(source)
            source_tier_mix[tier.value] = source_tier_mix.get(tier.value, 0) + 1
        signal_mix: dict[str, int] = {}
        for signal in context.report.evidence_signals:
            signal_mix[signal.signal_type.value] = signal_mix.get(signal.signal_type.value, 0) + 1
        evidence_section.summary = "Evidence appendix generated from claim-level sources and quality checks."
        evidence_section.content = {
            "claims": len(context.report.claims),
            "sources": len(context.report.sources),
            "snapshots": len(context.report.snapshots),
            "evidence_signals": len(context.report.evidence_signals),
            "evidence_table_rows": len(context.report.evidence_table_rows),
            "evidence_table_counts": _evidence_table_counts(context.report),
            "source_tier_mix": source_tier_mix,
            "signal_mix": signal_mix,
            "top_signals": _evidence_signal_summary(context, limit=12),
        }
        evidence_section.status = "complete"
        evidence_section.confidence_score = 1
        return context


class VerificationAgent(Agent):
    name = "Verification Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["claim_evidence_map", "quality_gate"]

    async def run(self, context: AgentContext) -> AgentContext:
        await _synthesize_into_section(
            context,
            self,
            "evidence_appendix",
            (
                "Review the claim/evidence map and summarize quality risks. "
                "Identify missing support, unavailable facts, and whether the report should pass. "
                "Do not create new business facts."
            ),
        )
        source_ids = {source.id for source in context.report.sources}
        source_by_id = {source.id: source for source in context.report.sources}
        blockers = []
        stale_evidence_claims = []
        for claim in context.report.claims:
            valid_source_links = claim.evidence_source_ids and all(source_id in source_ids for source_id in claim.evidence_source_ids)
            stale_only = False
            if valid_source_links and claim.claim_type != "unavailable" and _is_recency_sensitive_section(claim.section_id) and not _is_policy_or_guardrail_claim(claim.text):
                linked_sources = [source_by_id[source_id] for source_id in claim.evidence_source_ids if source_id in source_by_id]
                stale_only = bool(linked_sources) and all(
                    _source_is_stale_for_section(context, source, claim.section_id)
                    for source in linked_sources
                )
            if valid_source_links and not stale_only:
                claim.verification_status = "verified" if claim.claim_type != "unavailable" else "unavailable"
            else:
                claim.verification_status = "rejected"
                blockers.append(claim.id)
                if stale_only:
                    stale_evidence_claims.append(claim.id)
        refresh_evidence_tables(context)
        signal_count = len(context.report.evidence_signals)
        table_row_count = len(context.report.evidence_table_rows)
        claim_row_count = len([row for row in context.report.evidence_table_rows if row.row_type == "claim"])
        signal_row_count = len([row for row in context.report.evidence_table_rows if row.row_type == "signal"])
        strategic_signal_count = len(
            [
                signal
                for signal in context.report.evidence_signals
                if signal.signal_type
                in {
                    EvidenceSignalType.investment,
                    EvidenceSignalType.partnership_deal,
                    EvidenceSignalType.technology_stack,
                    EvidenceSignalType.hiring_footprint,
                    EvidenceSignalType.ai_strategy,
                    EvidenceSignalType.vendor_outsourcing,
                    EvidenceSignalType.it_investment,
                }
            ]
        )
        _replace_quality_check(
            context,
            QualityCheck(
                name="claim_level_traceability",
                passed=not blockers,
                severity="blocker" if blockers else "info",
                message=f"{len(blockers)} claims missing accepted evidence." if blockers else "All claims have evidence records.",
            )
        )
        _replace_quality_check(
            context,
            QualityCheck(
                name="freshness_sensitive_evidence",
                passed=not stale_evidence_claims,
                severity="blocker" if stale_evidence_claims else "info",
                message=(
                    f"{len(stale_evidence_claims)} freshness-sensitive claims rely only on stale baseline sources; examples: {stale_evidence_claims[:8]}."
                    if stale_evidence_claims
                    else "Freshness-sensitive claims are supported by recent or undated non-stale evidence."
                ),
            )
        )
        _replace_quality_check(
            context,
            QualityCheck(
                name="evidence_graph_signals",
                passed=signal_count > 0,
                severity="warning" if signal_count == 0 else "info",
                message=f"Evidence graph contains {signal_count} signals, including {strategic_signal_count} strategy-relevant investment/partnership/tech/hiring/AI/vendor/IT signals.",
            )
        )
        _replace_quality_check(
            context,
            QualityCheck(
                name="evidence_table_coverage",
                passed=claim_row_count >= len(context.report.claims) and signal_row_count >= len(context.report.evidence_signals),
                severity="warning" if claim_row_count < len(context.report.claims) or signal_row_count < len(context.report.evidence_signals) else "info",
                message=(
                    f"Evidence tables contain {table_row_count} rows: {claim_row_count}/{len(context.report.claims)} claims and "
                    f"{signal_row_count}/{len(context.report.evidence_signals)} evidence signals are tabularized."
                ),
            )
        )
        for section in context.report.sections:
            _normalize_section_evidence_language(context, section)
        return context


class ReportGeneratorAgent(Agent):
    name = "Report Generator Agent"
    model = "gpt-5.5"
    reasoning_effort = "high"
    tools = ["deck_spec", "pptx_renderer", "pdf_export"]

    async def run(self, context: AgentContext) -> AgentContext:
        _dedupe_report_claims(context.report)
        refresh_evidence_tables(context)
        sources_by_id = {source.id: source for source in context.report.sources}
        verified_claims = [claim for claim in context.report.claims if claim.verification_status == "verified"]
        unavailable_claims = [claim for claim in context.report.claims if claim.verification_status == "unavailable"]
        public_sources = [source for source in context.report.sources if source.url.startswith("http")]
        extracted_snapshots = [snapshot for snapshot in context.report.snapshots if snapshot.text_excerpt]
        supported_sections = [section.title for section in context.report.sections if section.status in {"complete", "partial"} and section.confidence_score >= 0.7]
        weak_sections = [section.title for section in context.report.sections if section.status == "unavailable" or section.confidence_score < 0.6]
        slides = [
            SlideSpec(
                id="cover",
                title=f"{context.report.company_name} Account Intelligence",
                layout="cover",
                bullets=[
                    f"Mode: {context.report.mode.value.title()}",
                    f"Freshness window: {context.report.freshness_window.value}",
                    f"{len(public_sources)} public sources | {len(extracted_snapshots)} snapshots | {len(context.report.claims)} claims | {len(context.report.evidence_signals)} signals | {len(context.report.evidence_table_rows)} table rows",
                ],
            )
        ]
        slides.append(
            SlideSpec(
                id="executive_readout",
                title="Executive Readout",
                layout="strategy",
                bullets=[
                    f"Verified claim base: {len(verified_claims)} verified claims; {len(unavailable_claims)} unavailable claims are explicitly marked.",
                    f"Strongest evidence coverage: {', '.join(supported_sections[:4]) or 'Evidence still developing'}.",
                    f"Open gaps to resolve before client-ready use: {', '.join(weak_sections[:4]) or 'No major section gaps flagged'}.",
                    "HCLTech pursuit guidance remains evidence-led and avoids forced capability mapping.",
                ],
                chart={
                    "type": "claim_status",
                    "title": "Claim Status",
                    "data": [
                        {"label": "Verified", "value": len(verified_claims)},
                        {"label": "Unavailable", "value": len(unavailable_claims)},
                        {"label": "Rejected", "value": len([claim for claim in context.report.claims if claim.verification_status == "rejected"])},
                        {"label": "Pending", "value": len([claim for claim in context.report.claims if claim.verification_status == "pending"])},
                    ],
                },
            )
        )
        credibility_counts: dict[str, int] = {}
        for source in public_sources:
            tier = (source.source_tier or _infer_source_tier(source)).value
            credibility_counts[tier] = credibility_counts.get(tier, 0) + 1
        slides.append(
            SlideSpec(
                id="source_mix",
                title="Source Mix and Evidence Depth",
                layout="evidence",
                bullets=[
                    f"{len(public_sources)} public sources captured across {len(credibility_counts)} source tiers.",
                    f"{len(extracted_snapshots)} extracted snapshots are available for synthesis.",
                    "Tier 1 sources support exact financials; Tier 2/3/4 sources support official or directional signals with labels.",
                ],
                chart={
                    "type": "source_mix",
                    "title": "Public Sources by Tier",
                    "data": [{"label": key.replace("_", " ").title(), "value": value} for key, value in sorted(credibility_counts.items())],
                },
            )
        )
        signal_counts: dict[str, int] = {}
        for signal in context.report.evidence_signals:
            signal_counts[signal.signal_type.value] = signal_counts.get(signal.signal_type.value, 0) + 1
        slides.append(
            SlideSpec(
                id="evidence_signals",
                title="Evidence Graph Signals",
                layout="evidence",
                bullets=[
                    f"{len(context.report.evidence_signals)} structured evidence signals available for cross-section synthesis.",
                    "Signals preserve the distinction between exact values, directional patterns, and inferred opportunities.",
                    "HCLTech strategy and consensus now read across this graph instead of relying on isolated section summaries.",
                ],
                chart={
                    "type": "signal_mix",
                    "title": "Evidence Signals by Type",
                    "data": [{"label": key.replace("_", " ").title(), "value": value} for key, value in sorted(signal_counts.items())],
                },
            )
        )
        table_counts = _evidence_table_counts(context.report)
        slides.append(
            SlideSpec(
                id="evidence_tables",
                title="Evidence Tables",
                layout="evidence",
                bullets=[
                    f"{len(context.report.evidence_table_rows)} loss-preserving table rows are available for analysis and drilldowns.",
                    "Every claim and evidence signal is represented as a table row, while source snapshots remain indexed so uncategorized context is not lost.",
                    "Typed tables accelerate synthesis without replacing the underlying source excerpts and citations.",
                ],
                chart={
                    "type": "table_mix",
                    "title": "Evidence Rows by Table",
                    "data": [{"label": key.replace("_", " ").title(), "value": value} for key, value in table_counts.items()],
                },
            )
        )
        slides.append(
            SlideSpec(
                id="section_coverage",
                title="Section Evidence Coverage",
                layout="evidence",
                bullets=[
                    "Coverage is measured by mapped claims and section confidence, not by visual polish.",
                    "Unavailable sections remain visible so the report fails closed instead of inventing analysis.",
                ],
                chart={
                    "type": "section_coverage",
                    "title": "Mapped Claims by Section",
                    "data": [
                        {
                            "label": section.title,
                            "value": len(section.claim_ids),
                            "confidence": section.confidence_score,
                            "status": section.status,
                        }
                        for section in context.report.sections
                    ],
                },
            )
        )
        for section in context.report.sections:
            section_claims = [claim for claim in context.report.claims if claim.id in section.claim_ids]
            citation_source_ids = []
            for claim in section_claims:
                citation_source_ids.extend(claim.evidence_source_ids)
            citation_source_ids = _rank_source_ids_for_section(
                context,
                list(dict.fromkeys(citation_source_ids)),
                section.id,
                limit=16,
                include_stale_if_needed=False,
            )
            bullets = _section_slide_bullets(context, section)
            speaker_notes = [
                f"Claim {claim.id}: {claim.text}"
                for claim in section_claims
            ]
            speaker_notes.extend(
                [
                    f"Source {source_id}: {sources_by_id[source_id].title} - {sources_by_id[source_id].url}"
                    for source_id in citation_source_ids
                    if source_id in sources_by_id
                ][:8]
            )
            slides.append(
                SlideSpec(
                    id=section.id,
                    title=section.title,
                    layout="strategy" if section.id in {"ai_strategy", "hcltech_penetration", "consensus"} else "section",
                    bullets=bullets[:5],
                    citation_source_ids=citation_source_ids,
                    speaker_notes=speaker_notes,
                )
            )
        context.report.deck_spec = DeckSpec(
            title=f"{context.report.company_name} Account Intelligence",
            subtitle="HCLTech market research portal",
            brand_tokens=css_tokens(),
            slides=slides,
        )
        _replace_quality_check(
            context,
            QualityCheck(name="deck_spec_created", passed=True, message=f"{len(slides)} slides specified."),
        )
        return context


class ExportQAAgent(Agent):
    name = "Export QA Agent"
    model = "gpt-5.5"
    reasoning_effort = "xhigh"
    tools = ["layout_checks", "citation_checks", "brand_palette_checks"]

    async def run(self, context: AgentContext) -> AgentContext:
        qa_check_names = {
            "deck_spec_available",
            "sources_available",
            "unsupported_claims_block",
            "source_depth_preflight",
            "reader_ready_content_preflight",
            "human_citation_preflight",
            "deep_research_required",
            "extracted_evidence_depth",
            "source_tier_mix_preflight",
            "evidence_signal_preflight",
            "evidence_table_preflight",
            "freshness_sensitive_evidence",
        }
        context.report.quality_checks = [check for check in context.report.quality_checks if check.name not in qa_check_names]
        has_deck = context.report.deck_spec is not None
        has_sources = bool(context.report.sources)
        public_sources = [source for source in context.report.sources if source.url.startswith("http")]
        unsupported = [claim.id for claim in context.report.claims if claim.verification_status == "rejected"]
        scaffold_terms = (
            "schema implemented",
            "hooks are ready",
            "metadata are configured",
            "source discovery is configured",
            "scaffold",
        )
        scaffold_sections = [
            section.title
            for section in context.report.sections
            if any(term in section.summary.lower() for term in scaffold_terms)
        ]
        raw_source_id_sections = [section.title for section in context.report.sections if "src_" in section.summary]
        source_floor = 20 if context.run.mode == ResearchMode.deep else 12
        source_depth_ok = len(public_sources) >= source_floor
        extracted_snapshots = [snapshot for snapshot in context.report.snapshots if snapshot.text_excerpt and len(snapshot.text_excerpt) >= 300]
        extraction_floor = 10 if context.run.mode == ResearchMode.deep else 3
        extraction_depth_ok = len(extracted_snapshots) >= extraction_floor
        tier_1_or_2_sources = [
            source
            for source in public_sources
            if (source.source_tier or _infer_source_tier(source))
            in {SourceTier.tier_1_official_financial, SourceTier.tier_2_official_company}
        ]
        signal_floor = 20 if context.run.mode == ResearchMode.deep else 8
        signal_depth_ok = len(context.report.evidence_signals) >= signal_floor
        table_floor = (len(context.report.claims) + len(context.report.evidence_signals)) if context.report.claims else 0
        table_depth_ok = len(context.report.evidence_table_rows) >= table_floor
        stale_sensitive_claims = _stale_sensitive_claim_ids(context)
        deep_research_checks = [check for check in context.report.quality_checks if check.name == "openai_deep_research_background"]
        deep_research_ok = bool(deep_research_checks and deep_research_checks[-1].passed) if context.run.mode == ResearchMode.deep else True
        reader_ready = not scaffold_sections
        scaffold_severity = "blocker" if context.run.mode == ResearchMode.deep and scaffold_sections else "warning"
        context.report.quality_checks.extend(
            [
                QualityCheck(
                    name="deck_spec_available",
                    passed=has_deck,
                    severity="blocker" if not has_deck else "info",
                    message="DeckSpec is available." if has_deck else "DeckSpec missing.",
                ),
                QualityCheck(
                    name="sources_available",
                    passed=has_sources,
                    severity="blocker" if not has_sources else "info",
                    message="Evidence sources are available." if has_sources else "No evidence sources found.",
                ),
                QualityCheck(
                    name="unsupported_claims_block",
                    passed=not unsupported,
                    severity="blocker" if unsupported else "info",
                    message=f"Rejected claims: {unsupported}" if unsupported else "No rejected claims.",
                ),
                QualityCheck(
                    name="source_depth_preflight",
                    passed=source_depth_ok,
                    severity="blocker" if context.run.mode == ResearchMode.deep and not source_depth_ok else "warning",
                    message=f"{len(public_sources)} public sources available; target floor is {source_floor}.",
                ),
                QualityCheck(
                    name="reader_ready_content_preflight",
                    passed=reader_ready,
                    severity=scaffold_severity if not reader_ready else "info",
                    message=(
                        f"Reader-facing scaffold language remains in: {', '.join(scaffold_sections[:6])}."
                        if scaffold_sections
                        else "No scaffold language detected in reader-facing summaries."
                    ),
                ),
                QualityCheck(
                    name="human_citation_preflight",
                    passed=not raw_source_id_sections,
                    severity="warning" if raw_source_id_sections else "info",
                    message=(
                        f"Internal source IDs appear in section summaries: {', '.join(raw_source_id_sections[:6])}."
                        if raw_source_id_sections
                        else "Section summaries do not expose internal source IDs."
                    ),
                ),
                QualityCheck(
                    name="deep_research_required",
                    passed=deep_research_ok,
                    severity="blocker" if context.run.mode == ResearchMode.deep and not deep_research_ok else "info",
                    message=(
                        "OpenAI Deep Research completed for this Deep Dive."
                        if deep_research_ok
                        else "Deep Dive requires a completed OpenAI Deep Research background run."
                    ),
                ),
                QualityCheck(
                    name="extracted_evidence_depth",
                    passed=extraction_depth_ok,
                    severity="blocker" if context.run.mode == ResearchMode.deep and not extraction_depth_ok else "info",
                    message=f"{len(extracted_snapshots)} extracted evidence snapshots available; target floor is {extraction_floor}.",
                ),
                QualityCheck(
                    name="source_tier_mix_preflight",
                    passed=bool(tier_1_or_2_sources),
                    severity="warning" if not tier_1_or_2_sources else "info",
                    message=f"{len(tier_1_or_2_sources)} Tier 1/Tier 2 public sources available for official financial/company evidence.",
                ),
                QualityCheck(
                    name="evidence_signal_preflight",
                    passed=signal_depth_ok,
                    severity="warning" if not signal_depth_ok else "info",
                    message=f"{len(context.report.evidence_signals)} evidence graph signals available; target floor is {signal_floor}.",
                ),
                QualityCheck(
                    name="evidence_table_preflight",
                    passed=table_depth_ok,
                    severity="warning" if not table_depth_ok else "info",
                    message=f"{len(context.report.evidence_table_rows)} evidence table rows available; target floor is {table_floor} claim+signal rows.",
                ),
                QualityCheck(
                    name="freshness_sensitive_evidence",
                    passed=not stale_sensitive_claims,
                    severity="blocker" if stale_sensitive_claims else "info",
                    message=(
                        f"{len(stale_sensitive_claims)} freshness-sensitive claims rely only on stale baseline sources; examples: {stale_sensitive_claims[:8]}."
                        if stale_sensitive_claims
                        else "Freshness-sensitive sections do not rely only on stale baseline sources."
                    ),
                ),
            ]
        )
        return context


QUICK_AGENT_SEQUENCE: list[Agent] = [
    PlannerAgent(),
    SourceDiscoveryAgent(),
    QuickSourceExpansionAgent(),
    CompanyOverviewAgent(),
    FinancialAgent(),
    RecentInvestmentsAgent(),
    PartnershipsDealsAgent(),
    AccountPrioritiesAgent(),
    TechnologyStackAgent(),
    HiringFootprintAgent(),
    NewsSignalsAgent(),
    ITSpendSignalsAgent(),
    OutsourcingVendorAgent(),
    ExecutiveAgent(),
    AIStrategyAgent(),
    HCLTechPenetrationAgent(),
    ConsensusAgent(),
    VerificationAgent(),
    ReportGeneratorAgent(),
    ExportQAAgent(),
]


DEEP_AGENT_SEQUENCE: list[Agent] = [
    PlannerAgent(),
    SourceDiscoveryAgent(),
    DeepResearchPlanningAgent(),
    OpenAIDeepResearchAgent(),
    DeepSourceExpansionAgent(),
    FirecrawlEvidenceExtractionAgent(),
    ApifySignalExtractionAgent(),
    GapCritiqueAgent(),
    RefinedSearchLoopAgent(),
    EvidenceHardeningAgent(),
    CompanyOverviewAgent(),
    FinancialAgent(),
    RecentInvestmentsAgent(),
    PartnershipsDealsAgent(),
    AccountPrioritiesAgent(),
    TechnologyStackAgent(),
    HiringFootprintAgent(),
    NewsSignalsAgent(),
    ITSpendSignalsAgent(),
    OutsourcingVendorAgent(),
    ExecutiveAgent(),
    AIStrategyAgent(),
    HCLTechPenetrationAgent(),
    ConsensusAgent(),
    VerificationAgent(),
    ReportGeneratorAgent(),
    ExportQAAgent(),
]


def get_agent_sequence(mode: ResearchMode) -> list[Agent]:
    if mode == ResearchMode.deep:
        return DEEP_AGENT_SEQUENCE
    return QUICK_AGENT_SEQUENCE


def new_report_for_run(run: ResearchRun) -> AccountReport:
    return AccountReport(
        run_id=run.id,
        company_name=run.company_name,
        mode=run.mode,
        freshness_window=run.freshness_window,
        sections=[],
        claims=[],
        sources=[],
    )
