# Cloud Run Deployment Notes

This scaffold is ready to containerize as two Cloud Run services:

- `market-research-api`: FastAPI backend from `backend/Dockerfile`
- `market-research-frontend`: React static frontend from `frontend/Dockerfile`

Current local hardening:

- `LocalRunStore` still owns canonical run JSON, but evidence rows are also persisted into a DuckDB sidecar at `data/evidence_mart.duckdb` for queryable table access, SQL summaries, semantic retrieval, drilldown acceleration, and report chat retrieval.
- `ResearchOrchestrator.execute_run()` now resumes from completed agent checkpoints instead of always discarding prior progress.
- `GET /api/reports/{run_id}/evidence-tables` exposes table counts and queryable evidence rows.
- `POST /api/reports/{run_id}/chat` retrieves rows from the DuckDB evidence mart and, when live providers are enabled, uses OpenAI embeddings for semantic search and `gpt-5.4-mini` to answer strictly from retrieved rows plus safe aggregate summaries.

Production follow-ups:

- Replace `LocalRunStore` with Cloud SQL PostgreSQL.
- Replace local artifact paths with Cloud Storage signed URLs.
- Add Secret Manager bindings for provider keys.
- Add Cloud Workflows for Deep Dive orchestration, using the persisted agent checkpoint state as the handoff contract.
- Add Cloud Tasks queues for agent workers and export QA; Cloud Run should receive task callbacks instead of relying on FastAPI `BackgroundTasks`.
- Add a shared access token or IAP when moving beyond prototype.
