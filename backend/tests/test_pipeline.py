from __future__ import annotations

import asyncio

from app.brand import BRAND_COLORS, SINGLE_COLOR_HEX
from app.config import Settings
from app.models import FreshnessWindow, ResearchMode, ResearchRunCreate
from app.services.orchestrator import ResearchOrchestrator
from app.services.task_dispatcher import should_use_cloud_tasks
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


def test_local_store_delete_removes_run_artifacts_and_evidence_rows(tmp_path):
    settings = Settings(data_dir=tmp_path, allow_live_providers=False)
    store = LocalRunStore(settings)
    orchestrator = ResearchOrchestrator(settings, store)
    run = orchestrator.create_run(
        ResearchRunCreate(company_name="DeleteCo", mode=ResearchMode.quick, freshness_window=FreshnessWindow.six_months)
    )
    completed = asyncio.run(orchestrator.execute_run(run.id))
    artifact_dir = settings.artifacts_dir / completed.id

    assert store.get(completed.id) is not None
    assert artifact_dir.exists()
    assert store.evidence_tables.table_counts(completed.id)

    result = store.delete(completed.id)

    assert result["deleted"] is True
    assert result["evidence_rows_deleted"] > 0
    assert result["artifacts_deleted"] >= 3
    assert store.get(completed.id) is None
    assert not artifact_dir.exists()
    assert store.evidence_tables.table_counts(completed.id) == {}


def test_execute_next_wave_persists_checkpoint_before_completion(tmp_path):
    settings = Settings(data_dir=tmp_path, allow_live_providers=False)
    store = LocalRunStore(settings)
    orchestrator = ResearchOrchestrator(settings, store)
    run = orchestrator.create_run(
        ResearchRunCreate(company_name="WaveCo", mode=ResearchMode.quick, freshness_window=FreshnessWindow.six_months)
    )

    checkpoint = asyncio.run(orchestrator.execute_next_wave(run.id))

    assert checkpoint.status != "completed"
    assert checkpoint.report is not None
    assert any(agent.status == "completed" for agent in checkpoint.agents)
    assert any(agent.status == "pending" for agent in checkpoint.agents)

    completed = asyncio.run(orchestrator.execute_run(run.id))

    assert completed.status == "completed"
    assert completed.progress == 100
    assert all(agent.status == "completed" for agent in completed.agents)


def test_department_lens_is_optional_and_checkpointed(tmp_path):
    settings = Settings(data_dir=tmp_path, allow_live_providers=False)
    store = LocalRunStore(settings)
    orchestrator = ResearchOrchestrator(settings, store)
    run = orchestrator.create_run(
        ResearchRunCreate(
            company_name="LensCo",
            department="Finance",
            mode=ResearchMode.quick,
            freshness_window=FreshnessWindow.six_months,
        )
    )

    assert run.department == "Finance"
    assert any(agent.name == "Department People Signal Agent" for agent in run.agents)

    checkpoint = asyncio.run(orchestrator.execute_next_wave(run.id))

    assert checkpoint.report is not None
    assert checkpoint.report.department == "Finance"
    assert any(section.id == "department_lens" and section.title == "Finance Department Lens" for section in checkpoint.report.sections)


def test_cloud_tasks_backend_detection():
    assert should_use_cloud_tasks(Settings(run_execution_backend="cloud_tasks")) is True
    assert should_use_cloud_tasks(Settings(run_execution_backend="tasks")) is True
    assert should_use_cloud_tasks(Settings(run_execution_backend="background_tasks")) is False
