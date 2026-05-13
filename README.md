# HCLTech Market Research Portal

Company-name-only account intelligence portal with a GCP-ready backend, branded web UI, editable PPTX export, PDF export, and claim-level evidence pack.

## What is implemented

- React/Vite frontend with mandatory brand palette tokens.
- FastAPI backend with the planned API surface:
  - `POST /api/runs`
  - `GET /api/runs/{run_id}`
  - `GET /api/reports/{run_id}`
  - `GET /api/reports/{run_id}/evidence`
  - `GET /api/reports/{run_id}/evidence-tables`
  - `GET /api/reports/{run_id}/artifacts/pptx`
  - `GET /api/reports/{run_id}/artifacts/pdf`
  - `POST /api/reports/{run_id}/drilldowns`
  - `POST /api/reports/{run_id}/chat`
- ADK-inspired plan/search/critique/refine/synthesize pipeline shape.
- Provider adapter pattern for OpenAI, Firecrawl, Apify, and future providers.
- Expanded quick/deep workflow contracts, including Deep Research, Firecrawl, Apify, Evidence Hardening, Source Discovery, and Export QA stages.
- Claim/evidence/source snapshot data model.
- DuckDB evidence mart for queryable report rows, safe SQL summaries, hybrid semantic/keyword retrieval, and grounded report chat.
- PPTX-first export plus PDF export.
- Local JSON/artifact storage for MVP development.

The backend runs safely without external API keys by returning source-aware scaffold output and unavailable fields instead of fabricated facts.

## Local development

### Backend

```powershell
cd g:\Antigravity\ADB_HCL\market-research-portal\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

Optional live provider keys:

```powershell
$env:OPENAI_API_KEY="..."
$env:FIRECRAWL_API_KEY="..."
$env:APIFY_API_TOKEN="..."
```

### Frontend

```powershell
cd g:\Antigravity\ADB_HCL\market-research-portal\frontend
npm install
npm run dev
```

Open the Vite URL and point it at `http://localhost:8000`.

### Backfill old local reports into DuckDB

If reports were generated before the DuckDB evidence mart existed, run:

```powershell
cd g:\Antigravity\ADB_HCL\market-research-portal
.\backend\.venv\Scripts\python.exe backend\scripts\backfill_evidence_mart.py --data-dir backend\data
```

This rebuilds `evidence_table_rows` from saved report JSON and writes them into `backend\data\evidence_mart.duckdb`. Chat embeddings are created lazily the first time a report is queried.

## GCP readiness

The current code is Cloud Run friendly. The next deployment pass should add:

- Cloud SQL implementation for `RunStore`.
- Cloud Storage implementation for artifacts and source snapshots.
- Cloud Tasks/Workflows orchestration adapter.
- Secret Manager configuration injection.
- Cloud Build pipeline.
