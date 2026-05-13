from __future__ import annotations

import asyncio

from app.brand import BRAND_COLORS, SINGLE_COLOR_HEX
from app.config import Settings
from app.models import FreshnessWindow, ResearchMode, ResearchRunCreate
from app.services.orchestrator import ResearchOrchestrator
from app.storage.local_store import LocalRunStore


def test_brand_palette_contains_required_dark_blue():
    assert BRAND_COLORS["dark_blue"].hex == "#0F5FDC"
    assert SINGLE_COLOR_HEX == "#0F5FDC"


def test_pipeline_generates_report_and_artifacts(tmp_path):
    settings = Settings(data_dir=tmp_path, allow_live_providers=False)
    store = LocalRunStore(settings)
    orchestrator = ResearchOrchestrator(settings, store)
    run = orchestrator.create_run(
        ResearchRunCreate(company_name="Oracle Corporation", mode=ResearchMode.quick, freshness_window=FreshnessWindow.six_months)
    )

    completed = asyncio.run(orchestrator.execute_run(run.id))

    assert completed.status == "completed"
    assert completed.report is not None
    assert completed.report.deck_spec is not None
    assert {artifact.kind for artifact in completed.report.artifacts} == {"pptx", "pdf", "evidence_json"}
    assert all(claim.evidence_source_ids for claim in completed.report.claims)
    assert all(check.passed for check in completed.report.quality_checks if check.severity == "blocker")

