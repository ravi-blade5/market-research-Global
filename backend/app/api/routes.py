from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.models import DrilldownRequest, DrilldownRun, ResearchRunCreate, RunStatus
from app.services.orchestrator import ResearchOrchestrator
from app.services.report_chat import ReportChatService
from app.services.task_dispatcher import RunTaskDispatcher, should_use_cloud_tasks
from app.storage.factory import create_run_store
from app.storage.gcs_artifacts import GCSArtifactStore

router = APIRouter(prefix="/api")
store = create_run_store(settings)
orchestrator = ResearchOrchestrator(settings, store)
report_chat = ReportChatService(settings)
artifact_store = GCSArtifactStore(settings.gcs_artifact_bucket) if settings.artifact_backend.lower() == "gcs" and settings.gcs_artifact_bucket else None
task_dispatcher = RunTaskDispatcher(settings) if should_use_cloud_tasks(settings) else None


@router.post("/runs")
async def create_run(request: ResearchRunCreate, background_tasks: BackgroundTasks):
    run = orchestrator.create_run(request)
    if task_dispatcher:
        task_name = task_dispatcher.enqueue_run(run.id)
        run.run_notes.append(f"Dispatched through Cloud Tasks: {task_name}")
        store.save(run)
    else:
        background_tasks.add_task(orchestrator.execute_run, run.id)
    return run


@router.post("/runs/{run_id}/execute-task")
async def execute_run_task(run_id: str, x_task_dispatch_token: str | None = Header(default=None)):
    if not settings.task_dispatch_token or x_task_dispatch_token != settings.task_dispatch_token:
        raise HTTPException(status_code=403, detail="Invalid task dispatch token")
    try:
        run = await orchestrator.execute_next_wave(run_id)
        if task_dispatcher and run.status not in {RunStatus.completed, RunStatus.failed}:
            task_name = task_dispatcher.enqueue_run(run.id)
            run.run_notes.append(f"Queued next checkpoint wave through Cloud Tasks: {task_name}")
            store.save(run)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/execute")
async def execute_run_now(run_id: str):
    try:
        return await orchestrator.execute_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/history")
async def list_run_history():
    return [
        {
            "id": run.id,
            "company_name": run.company_name,
            "department": run.department,
            "mode": run.mode,
            "freshness_window": run.freshness_window,
            "status": run.status,
            "progress": run.progress,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "has_report": bool(run.report),
            "claim_count": len(run.report.claims) if run.report else 0,
            "source_count": len(run.report.sources) if run.report else 0,
            "signal_count": len(run.report.evidence_signals) if run.report else 0,
            "table_row_count": len(run.report.evidence_table_rows) if run.report else 0,
        }
        for run in store.list()
    ]


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    result = store.delete(run_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="Run not found")
    if artifact_store is not None:
        result["artifacts_deleted"] = int(result.get("artifacts_deleted", 0)) + artifact_store.delete_run_artifacts(run_id)
    return result


@router.get("/runs")
async def list_runs():
    return [run for run in store.list()]


@router.get("/reports/{run_id}")
async def get_report(run_id: str):
    run = store.get(run_id)
    if not run or not run.report:
        raise HTTPException(status_code=404, detail="Report not found")
    return run.report


@router.get("/reports/{run_id}/evidence")
async def get_evidence(run_id: str):
    run = store.get(run_id)
    if not run or not run.report:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {
        "run_id": run.id,
        "claims": run.report.claims,
        "sources": run.report.sources,
        "snapshots": run.report.snapshots,
        "extracted_values": run.report.extracted_values,
        "evidence_signals": run.report.evidence_signals,
        "evidence_table_rows": run.report.evidence_table_rows,
        "quality_checks": run.report.quality_checks,
        "rejected_claims": run.report.rejected_claims,
    }


@router.get("/reports/{run_id}/evidence-tables")
async def get_evidence_tables(run_id: str, table_name: str | None = None, limit: int = 200):
    run = store.get(run_id)
    if not run or not run.report:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {
        "run_id": run.id,
        "counts": store.evidence_tables.table_counts(run.id),
        "rows": store.evidence_tables.list_rows(run.id, table_name=table_name, limit=limit),
    }


@router.get("/reports/{run_id}/artifacts/{kind}")
async def get_artifact(run_id: str, kind: str):
    if kind not in {"pptx", "pdf", "evidence_json"}:
        raise HTTPException(status_code=400, detail="Unsupported artifact kind")
    run = store.get(run_id)
    if not run or not run.report:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = next((item for item in run.report.artifacts if item.kind == kind), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf": "application/pdf",
        "evidence_json": "application/json",
    }[kind]
    if artifact.path.startswith("gs://"):
        if artifact_store is None:
            raise HTTPException(status_code=500, detail="GCS artifact backend is not configured")
        local_path = settings.artifacts_dir / run_id / artifact.path.rsplit("/", 1)[-1]
        artifact_store.download_to_file(artifact.path, local_path)
        return FileResponse(str(local_path), media_type=media_type, filename=local_path.name)
    return FileResponse(artifact.path, media_type=media_type, filename=artifact.path.split("\\")[-1].split("/")[-1])


@router.post("/reports/{run_id}/drilldowns")
async def create_drilldown(run_id: str, request: DrilldownRequest):
    run = store.get(run_id)
    if not run or not run.report:
        raise HTTPException(status_code=404, detail="Report not found")
    evidence_rows, analytics, retrieval_mode = await report_chat.retrieve(
        run=run,
        question=request.question,
        evidence_store=store.evidence_tables,
        limit=request.max_evidence_rows,
    )
    return await report_chat.answer(
        run=run,
        question=request.question,
        evidence_rows=evidence_rows,
        analytics=analytics,
        retrieval_mode=retrieval_mode,
    )


@router.post("/reports/{run_id}/chat")
async def chat_with_report(run_id: str, request: DrilldownRequest):
    return await create_drilldown(run_id, request)


@router.get("/reports")
async def list_reports():
    return [run for run in store.list()]


@router.get("/provider-status")
async def provider_status():
    return {
        "allow_live_providers": settings.allow_live_providers,
        "openai_api_key_loaded": bool(settings.openai_api_key),
        "firecrawl_api_key_loaded": bool(settings.firecrawl_api_key),
        "apify_api_token_loaded": bool(settings.apify_api_token),
        "openai_analysis_model": settings.openai_analysis_model,
        "openai_extraction_model": settings.openai_extraction_model,
        "openai_deep_research_model": settings.openai_deep_research_model,
        "openai_embedding_model": settings.openai_embedding_model,
        "openai_embedding_dimensions": settings.openai_embedding_dimensions,
        "openai_search_reasoning_effort": settings.openai_search_reasoning_effort,
        "openai_search_timeout_seconds": settings.openai_search_timeout_seconds,
        "openai_synthesis_evidence_limit": settings.openai_synthesis_evidence_limit,
        "openai_synthesis_max_output_tokens": settings.openai_synthesis_max_output_tokens,
        "openai_synthesis_timeout_seconds": settings.openai_synthesis_timeout_seconds,
        "openai_deep_research_max_tool_calls": settings.openai_deep_research_max_tool_calls,
        "firecrawl_max_sources_per_run": settings.firecrawl_max_sources_per_run,
        "apify_actor_id": settings.apify_actor_id,
        "apify_max_crawl_pages": settings.apify_max_crawl_pages,
        "apify_people_actor_id": settings.apify_people_actor_id,
        "apify_people_profile_scraper_mode": settings.apify_people_profile_scraper_mode,
        "apify_people_dataset_item_limit": settings.apify_people_dataset_item_limit,
        "agent_parallelism": settings.agent_parallelism,
        "run_execution": settings.run_execution_backend,
        "cloud_tasks_queue": settings.cloud_tasks_queue,
        "cloud_tasks_location": settings.cloud_tasks_location,
        "task_dispatch_token_loaded": bool(settings.task_dispatch_token),
        "run_store_backend": settings.run_store_backend,
        "artifact_backend": settings.artifact_backend,
        "gcs_artifact_bucket": settings.gcs_artifact_bucket,
        "evidence_table_store": str(store.evidence_tables.path),
        "evidence_table_engine": "postgres" if settings.run_store_backend.lower() in {"postgres", "postgresql", "cloudsql", "cloud_sql"} else "duckdb",
        "report_chat_retrieval": "sql_plus_embeddings_when_live",
        "report_chat_model": settings.openai_extraction_model,
    }
