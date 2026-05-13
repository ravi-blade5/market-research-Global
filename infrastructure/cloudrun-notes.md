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
- GCP mode uses `RUN_EXECUTION_BACKEND=cloud_tasks`: `POST /api/runs` persists the run and enqueues a Cloud Tasks callback to `POST /api/runs/{run_id}/execute-task`.
- The Cloud Tasks callback executes one pending orchestration wave, saves the checkpoint, and only then enqueues the next Cloud Tasks callback. This keeps Deep Dive durable across long provider steps instead of relying on one long HTTP request.
- The Cloud Tasks callback is protected by `TASK_DISPATCH_TOKEN` in Secret Manager. Cloud Tasks retries are safe because the orchestrator persists completed agent checkpoints and resumes already-completed groups.

Production follow-ups:

- Use `infrastructure/gcp-setup.ps1` to enable APIs, create the service account, Artifact Registry repo, GCS bucket, Cloud SQL instance/database/user, and baseline IAM.
- Use `infrastructure/gcp-sync-secrets.ps1` to sync `OPENAI_API_KEY`, `FIRECRAWL_API_KEY`, and `APIFY_API_TOKEN` from `backend/.env` into Secret Manager.
- Use `infrastructure/gcp-deploy.ps1` to deploy the API and web Cloud Run services.
- Cloud Tasks queue default: `market-research-runs`, configured with low dispatch rate and retry backoff for quality-first Deep Dive execution.
- Future refinement: use Cloud Workflows to make the wave chain externally visible in GCP, but the API already dispatches checkpointed agent waves through Cloud Tasks.
- Add a shared access token or IAP when moving beyond prototype.
