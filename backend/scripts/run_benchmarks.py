from __future__ import annotations

import argparse
import asyncio
import json
import sys
from zipfile import ZipFile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings
from app.models import FreshnessWindow, ResearchMode, ResearchRunCreate
from app.services.exporter import _insight_inventory
from app.services.orchestrator import ResearchOrchestrator
from app.storage.local_store import LocalRunStore


DEFAULT_COMPANIES = ["Infosys", "Oracle Corporation"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live benchmark research jobs and write a compact quality summary.")
    parser.add_argument("--companies", nargs="+", default=DEFAULT_COMPANIES)
    parser.add_argument("--modes", nargs="+", choices=["quick", "deep"], default=["quick"])
    parser.add_argument("--freshness-window", choices=["6m", "12m"], default="12m")
    parser.add_argument("--data-dir", type=Path, default=Path("./data"))
    parser.add_argument("--output-dir", type=Path, default=Path("./data/benchmarks"))
    return parser.parse_args()


def _artifact_paths(report) -> dict[str, str]:
    return {artifact.kind: artifact.path for artifact in report.artifacts}


def _pptx_slide_count(path: str | None) -> int | None:
    if not path:
        return None
    artifact_path = Path(path)
    if not artifact_path.exists():
        return None
    with ZipFile(artifact_path) as package:
        return len([name for name in package.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")])


def _summary_for_run(run, elapsed_seconds: float) -> dict:
    report = run.report
    if not report:
        return {
            "run_id": run.id,
            "company": run.company_name,
            "mode": run.mode.value,
            "status": run.status.value,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "error": run.error,
        }
    blockers = [check for check in report.quality_checks if check.severity == "blocker" and not check.passed]
    warnings = [check for check in report.quality_checks if check.severity == "warning" and not check.passed]
    public_sources = [source for source in report.sources if source.url.startswith("http")]
    extracted_snapshots = [snapshot for snapshot in report.snapshots if snapshot.text_excerpt]
    artifact_paths = _artifact_paths(report)
    evidence_table_rows = len(report.evidence_table_rows)
    insight_inventory = _insight_inventory(report, limit_per_section=7)
    return {
        "run_id": run.id,
        "company": run.company_name,
        "mode": run.mode.value,
        "status": run.status.value,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "sections": len(report.sections),
        "claims": len(report.claims),
        "verified_claims": len([claim for claim in report.claims if claim.verification_status == "verified"]),
        "public_sources": len(public_sources),
        "snapshots": len(extracted_snapshots),
        "evidence_signals": len(report.evidence_signals),
        "evidence_table_rows": evidence_table_rows,
        "insight_inventory_sections": len(insight_inventory),
        "pptx_slides": _pptx_slide_count(artifact_paths.get("pptx")),
        "blockers": [{"name": check.name, "message": check.message} for check in blockers],
        "warnings": [{"name": check.name, "message": check.message} for check in warnings],
        "artifacts": artifact_paths,
    }


async def _run_one(orchestrator: ResearchOrchestrator, company: str, mode: str, freshness_window: FreshnessWindow) -> dict:
    request = ResearchRunCreate(
        company_name=company,
        mode=ResearchMode(mode),
        freshness_window=freshness_window,
    )
    run = orchestrator.create_run(request)
    start = perf_counter()
    completed = await orchestrator.execute_run(run.id)
    return _summary_for_run(completed, perf_counter() - start)


async def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=args.data_dir, allow_live_providers=True)
    orchestrator = ResearchOrchestrator(settings, LocalRunStore(settings))
    freshness_window = FreshnessWindow(args.freshness_window)
    summaries = []
    for company in args.companies:
        for mode in args.modes:
            print(f"Running {mode} benchmark for {company}...", flush=True)
            try:
                summaries.append(await _run_one(orchestrator, company, mode, freshness_window))
            except Exception as exc:
                summaries.append(
                    {
                        "company": company,
                        "mode": mode,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
            print(json.dumps(summaries[-1], indent=2), flush=True)

    output_path = args.output_dir / f"benchmark_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "runs": summaries}, indent=2), encoding="utf-8")
    print(f"Benchmark summary written to {output_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
