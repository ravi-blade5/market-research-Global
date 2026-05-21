from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    data_dir: Path = Path("./data")
    run_store_backend: str = "local"
    artifact_backend: str = "local"
    database_url: str | None = None
    gcp_project_id: str | None = None
    gcp_region: str = "us-central1"
    gcs_artifact_bucket: str | None = None
    cors_allow_origins: str = "*"
    run_execution_backend: str = "background_tasks"
    public_base_url: str | None = None
    cloud_tasks_queue: str = "market-research-runs"
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_dispatch_deadline_seconds: int = 1800
    task_dispatch_token: str | None = None
    openai_api_key: str | None = None
    firecrawl_api_key: str | None = None
    apify_api_token: str | None = None
    shared_access_token: str | None = None
    openai_analysis_model: str = "gpt-5.5"
    openai_extraction_model: str = "gpt-5.4-mini"
    openai_deep_research_model: str = "o3-deep-research"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 512
    report_chat_embedding_batch_size: int = 96
    report_chat_embedding_max_rows: int = 1500
    openai_search_reasoning_effort: str = "high"
    openai_search_timeout_seconds: int = 180
    openai_synthesis_evidence_limit: int = 60
    openai_synthesis_max_output_tokens: int = 12000
    openai_synthesis_timeout_seconds: int = 420
    openai_json_repair_max_output_tokens: int = 8000
    openai_deep_research_max_tool_calls: int = 120
    openai_deep_research_timeout_seconds: int = 7200
    openai_deep_research_poll_interval_seconds: int = 10
    firecrawl_max_sources_per_run: int = 30
    firecrawl_wait_timeout_seconds: int = 300
    firecrawl_poll_interval_seconds: int = 5
    firecrawl_concurrency: int = 3
    apify_actor_id: str = "apify~website-content-crawler"
    apify_max_crawl_pages: int = 20
    apify_wait_timeout_seconds: int = 300
    apify_dataset_item_limit: int = 30
    apify_people_actor_id: str = "harvestapi~linkedin-company-employees"
    apify_people_profile_scraper_mode: str = "Full ($8 per 1k)"
    apify_people_wait_timeout_seconds: int = 300
    apify_people_dataset_item_limit: int = 50
    allow_live_providers: bool = False
    agent_parallelism: int = 4

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"


settings = Settings()
