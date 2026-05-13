from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.base import AgentContext
from app.agents.pipeline import refresh_evidence_tables
from app.config import Settings
from app.models import ResearchRun
from app.providers.registry import ProviderRegistry
from app.storage.local_store import LocalRunStore


def _raw_run_payloads(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_raw_run_payloads(path: Path, payloads: dict[str, dict[str, Any]]) -> None:
    path.write_text(json.dumps(payloads, indent=2, default=str), encoding="utf-8")


def backfill(*, data_dir: Path, only_run_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    settings = Settings(data_dir=data_dir, allow_live_providers=False)
    store = LocalRunStore(settings)
    payloads = _raw_run_payloads(store.path)
    providers = ProviderRegistry(settings)
    summary: dict[str, Any] = {
        "data_dir": str(settings.data_dir),
        "runs_path": str(store.path),
        "evidence_mart": str(store.evidence_tables.path),
        "dry_run": dry_run,
        "total_runs": len(payloads),
        "processed": 0,
        "skipped": 0,
        "backfilled": [],
    }

    for run_id, raw in payloads.items():
        if only_run_id and run_id != only_run_id:
            continue
        run = ResearchRun.model_validate(raw)
        if not run.report:
            summary["skipped"] += 1
            continue

        before_rows = len(run.report.evidence_table_rows)
        context = AgentContext(run=run, report=run.report, providers=providers)
        refresh_evidence_tables(context)
        after_rows = len(run.report.evidence_table_rows)
        if not dry_run:
            raw["report"] = run.report.model_dump(mode="json")
            payloads[run_id] = raw
            store.evidence_tables.replace_report_rows(run.report)
        summary["processed"] += 1
        summary["backfilled"].append(
            {
                "run_id": run.id,
                "company_name": run.company_name,
                "status": run.status,
                "before_rows": before_rows,
                "after_rows": after_rows,
                "claims": len(run.report.claims),
                "sources": len(run.report.sources),
                "signals": len(run.report.evidence_signals),
            }
        )

    if not dry_run:
        _write_raw_run_payloads(store.path, payloads)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill completed/local reports into the DuckDB evidence mart.")
    parser.add_argument("--data-dir", default="./data", help="Backend data directory containing runs.json.")
    parser.add_argument("--run-id", default=None, help="Optionally backfill a single run.")
    parser.add_argument("--dry-run", action="store_true", help="Compute backfill counts without writing.")
    args = parser.parse_args()

    summary = backfill(data_dir=Path(args.data_dir), only_run_id=args.run_id, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
