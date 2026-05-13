from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GTMChannel:
    id: str
    name: str
    category: str
    keywords: tuple[str, ...]
    motion: str
    proof_asset: str
    success_metric: str
    trap_to_avoid: str


GTM_CHANNEL_CATALOG: tuple[GTMChannel, ...] = (
    GTMChannel(
        id="enterprise_sales",
        name="Enterprise Sales",
        category="Targeted Acquisition",
        keywords=(
            "executive",
            "cfo",
            "cio",
            "cto",
            "chief",
            "procurement",
            "buying center",
            "transformation",
            "cost",
            "modernization",
            "governance",
        ),
        motion="Run account-based executive outreach anchored to one measurable business or operating outcome.",
        proof_asset="one-page executive value hypothesis and 30-minute discovery agenda",
        success_metric="executive meeting secured and buying-center sponsor identified",
        trap_to_avoid="Do not lead with generic capability mapping before the account pain and sponsor are validated.",
    ),
    GTMChannel(
        id="business_development_alliance",
        name="Business Development / Alliance Motion",
        category="Ecosystem & Partnerships",
        keywords=(
            "partnership",
            "alliance",
            "ecosystem",
            "hyperscaler",
            "aws",
            "azure",
            "google cloud",
            "microsoft",
            "oracle",
            "sap",
            "snowflake",
            "databricks",
            "palantir",
            "anthropic",
            "nvidia",
        ),
        motion="Co-sell or co-innovate through the account's current strategic technology partner ecosystem.",
        proof_asset="partner-aligned solution sketch with roles, integration points, and mutual value narrative",
        success_metric="joint account workshop or partner-qualified opportunity created",
        trap_to_avoid="Do not assume partner access exists; validate account-team and partner-team sponsorship first.",
    ),
    GTMChannel(
        id="cloud_marketplace_private_offer",
        name="Cloud Marketplace / Private Offer",
        category="Ecosystem & Partnerships",
        keywords=(
            "cloud",
            "aws",
            "azure",
            "gcp",
            "google cloud",
            "marketplace",
            "private offer",
            "procurement",
            "commit",
            "consumption",
            "migration",
        ),
        motion="Package the pilot as a cloud-funded or marketplace-friendly private-offer path to reduce procurement friction.",
        proof_asset="marketplace-ready pilot scope, commercial path, and cloud-credit/value case",
        success_metric="procurement path confirmed and pilot funding route identified",
        trap_to_avoid="Do not propose a marketplace motion without checking procurement fit and cloud-commit incentives.",
    ),
    GTMChannel(
        id="existing_platform_integration",
        name="Existing Platform / Integration Motion",
        category="Ecosystem & Partnerships",
        keywords=(
            "sap",
            "oracle",
            "salesforce",
            "servicenow",
            "workday",
            "microsoft 365",
            "teams",
            "slack",
            "snowflake",
            "databricks",
            "integration",
            "workflow",
            "platform",
        ),
        motion="Meet users inside the platforms already visible in the account's estate and frame the work as workflow acceleration.",
        proof_asset="integration storyboard or clickable workflow prototype using the account's known platform context",
        success_metric="platform owner validates workflow fit and data/integration path",
        trap_to_avoid="Do not offer a shallow integration that looks disconnected from the business process.",
    ),
    GTMChannel(
        id="engineering_as_marketing",
        name="Engineering-as-Marketing Pilot",
        category="Community & Product",
        keywords=(
            "pilot",
            "poc",
            "proof of concept",
            "benchmark",
            "assessment",
            "diagnostic",
            "developer",
            "engineering",
            "platform engineering",
            "automation",
            "agentic",
            "ai",
        ),
        motion="Build a small diagnostic, benchmark, or prototype that demonstrates value before a broad transformation ask.",
        proof_asset="source-backed diagnostic report, working demo, or quantified benchmark",
        success_metric="pilot sponsor agrees to success criteria and next-step commercial path",
        trap_to_avoid="Do not build a clever demo that is not tied to a validated account problem.",
    ),
    GTMChannel(
        id="executive_thought_leadership",
        name="Executive Thought Leadership",
        category="Content & Brand",
        keywords=(
            "ai strategy",
            "responsible ai",
            "governance",
            "risk",
            "regulation",
            "operating model",
            "innovation",
            "autonomous",
            "agentic",
            "data strategy",
        ),
        motion="Use a tailored executive briefing to shape the narrative before proposing delivery work.",
        proof_asset="board-style briefing with account-specific evidence, risks, and 90-day options",
        success_metric="executive sponsor requests a follow-up workshop or internal briefing pack",
        trap_to_avoid="Do not make the briefing a sales pitch; teach the account something specific about its own signals.",
    ),
    GTMChannel(
        id="field_event_workshop",
        name="Field Event / Executive Workshop",
        category="Physical & High-Touch",
        keywords=(
            "sapphire",
            "summit",
            "conference",
            "forum",
            "mwc",
            "re:invent",
            "ignite",
            "event",
            "workshop",
            "roundtable",
        ),
        motion="Turn a market or vendor event into a focused account workshop with pre-booked follow-up actions.",
        proof_asset="event-specific executive agenda, demo station, and post-event follow-up plan",
        success_metric="qualified follow-up meetings booked within two weeks of the event",
        trap_to_avoid="Do not treat the event as badge collection; pre-wire the target conversations.",
    ),
    GTMChannel(
        id="account_based_content",
        name="Account-Based Content",
        category="Content & Brand",
        keywords=(
            "case study",
            "whitepaper",
            "benchmark",
            "research",
            "thought leadership",
            "customer story",
            "industry report",
            "roadmap",
        ),
        motion="Create a targeted account narrative that connects public signals to a decision-ready business case.",
        proof_asset="account-specific point of view, benchmark, or value hypothesis deck",
        success_metric="stakeholder shares the narrative internally or asks for a tailored workshop",
        trap_to_avoid="Do not publish generic content that fails to reflect the account's current priorities.",
    ),
)


def rank_gtm_channels(corpus: str, *, limit: int = 8) -> list[tuple[GTMChannel, int]]:
    normalized = corpus.lower()
    ranked: list[tuple[GTMChannel, int]] = []
    for channel in GTM_CHANNEL_CATALOG:
        score = sum(1 for keyword in channel.keywords if keyword in normalized)
        if score:
            ranked.append((channel, score))
    if not ranked:
        ranked = [
            (channel, 1)
            for channel in GTM_CHANNEL_CATALOG
            if channel.id in {"enterprise_sales", "engineering_as_marketing", "executive_thought_leadership"}
        ]
    ranked.sort(key=lambda item: (-item[1], item[0].category, item[0].name))
    return ranked[:limit]
