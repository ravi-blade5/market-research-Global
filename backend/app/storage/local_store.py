from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.config import Settings
from app.models import ResearchRun
from app.storage.evidence_store import EvidenceTableStore


class LocalRunStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.settings.data_dir / "runs.json"
        self.evidence_tables = EvidenceTableStore(self.settings.data_dir)

    def _read_all(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_all(self, data: dict[str, dict]) -> None:
        self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def save(self, run: ResearchRun) -> ResearchRun:
        data = self._read_all()
        data[run.id] = run.model_dump(mode="json")
        self._write_all(data)
        if run.report and run.report.evidence_table_rows:
            self.evidence_tables.replace_report_rows(run.report)
        return run

    def get(self, run_id: str) -> ResearchRun | None:
        data = self._read_all()
        raw = data.get(run_id)
        if not raw:
            return None
        return ResearchRun.model_validate(raw)

    def delete(self, run_id: str) -> dict[str, int | bool | str]:
        data = self._read_all()
        if run_id not in data:
            return {"deleted": False, "run_id": run_id, "evidence_rows_deleted": 0, "artifacts_deleted": 0}

        del data[run_id]
        self._write_all(data)
        evidence_rows_deleted = self.evidence_tables.delete_run(run_id)
        run_dir = self.settings.artifacts_dir / run_id
        artifacts_deleted = 0
        if run_dir.exists() and run_dir.is_dir():
            artifacts_deleted = sum(1 for item in run_dir.rglob("*") if item.is_file())
            shutil.rmtree(run_dir)
        return {
            "deleted": True,
            "run_id": run_id,
            "evidence_rows_deleted": evidence_rows_deleted,
            "artifacts_deleted": artifacts_deleted,
        }

    def list(self) -> list[ResearchRun]:
        data = self._read_all()
        return [ResearchRun.model_validate(raw) for raw in data.values()]

    def artifact_path(self, run_id: str, suffix: str) -> Path:
        run_dir = self.settings.artifacts_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / f"{run_id}.{suffix}"
