# Cloud Run Deployment Notes

This scaffold is ready to containerize as two Cloud Run services:

- `market-research-portal-api`: FastAPI backend from `backend/Dockerfile`
- `market-research-portal-web`: React static frontend from `frontend/Dockerfile`

Target project confirmed for this migration:

- Google profile: `rvkumar31@gmail.com`
- Project ID: `project-c6c8a787-a2c7-48b7-8b0`
- Region default: `us-central1`
- GCS bucket default: `project-c6c8a787-a2c7-48b7-8b0-market-research-artifacts`
- Cloud SQL instance default: `market-research-db`
- Database default: `market_research`
- Service account default: `market-research-runner`

Current local hardening:

- Local mode uses `LocalRunStore` with canonical run JSON and DuckDB sidecar at `data/evidence_mart.duckdb`.
- GCP mode uses `RUN_STORE_BACKEND=postgres` to persist canonical runs and evidence rows in Cloud SQL PostgreSQL.
- GCP mode uses `ARTIFACT_BACKEND=gcs` to upload PPTX, PDF, and evidence packs to Cloud Storage.
- `ResearchOrchestrator.execute_run()` now resumes from completed agent checkpoints instead of always discarding prior progress.
- `GET /api/reports/{run_id}/evidence-tables` exposes table counts and queryable evidence rows.
- `POST /api/reports/{run_id}/chat` retrieves rows from the DuckDB evidence mart and, when live providers are enabled, uses OpenAI embeddings for semantic search and `gpt-5.4-mini` to answer strictly from retrieved rows plus safe aggregate summaries.

Production follow-ups:

- Use `infrastructure/gcp-setup.ps1` to enable APIs, create the service account, Artifact Registry repo, GCS bucket, Cloud SQL instance/database/user, and baseline IAM.
- Use `infrastructure/gcp-sync-secrets.ps1` to sync `OPENAI_API_KEY`, `FIRECRAWL_API_KEY`, and `APIFY_API_TOKEN` from `backend/.env` into Secret Manager.
- Use `infrastructure/gcp-deploy.ps1` to deploy the API and web Cloud Run services.
- Add Cloud Workflows for Deep Dive orchestration, using the persisted agent checkpoint state as the handoff contract.
- Add Cloud Tasks queues for agent workers and export QA; Cloud Run should receive task callbacks instead of relying on FastAPI `BackgroundTasks`.
- Add a shared access token or IAP when moving beyond prototype.
