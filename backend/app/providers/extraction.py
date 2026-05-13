from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import ExtractedPage, ExtractionJobResult, ExtractionProvider


def _metadata_to_str(metadata: dict[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (metadata or {}).items() if v is not None}


def _firecrawl_page_from_payload(payload: dict[str, Any], fallback_url: str) -> ExtractedPage:
    metadata = payload.get("metadata") or {}
    url = metadata.get("sourceURL") or metadata.get("url") or payload.get("url") or fallback_url
    return ExtractedPage(
        url=str(url),
        title=str(metadata.get("title") or url),
        text=str(payload.get("markdown") or payload.get("content") or payload.get("html") or ""),
        metadata=_metadata_to_str(metadata),
    )


def _apify_page_from_item(item: dict[str, Any], fallback_url: str) -> ExtractedPage:
    url = item.get("url") or item.get("loadedUrl") or item.get("sourceUrl") or fallback_url
    text = (
        item.get("markdown")
        or item.get("text")
        or item.get("content")
        or item.get("pageContent")
        or item.get("body")
        or ""
    )
    metadata = {
        "title": item.get("title") or item.get("metadata", {}).get("title") if isinstance(item.get("metadata"), dict) else item.get("title"),
        "status": item.get("statusCode") or item.get("status"),
        "source": "apify_dataset",
    }
    return ExtractedPage(
        url=str(url),
        title=str(item.get("title") or url),
        text=str(text),
        metadata=_metadata_to_str(metadata),
    )


class FirecrawlExtractionProvider(ExtractionProvider):
    name = "firecrawl"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract_url(self, url: str) -> ExtractedPage:
        if not self.settings.firecrawl_api_key:
            return ExtractedPage(
                url=url,
                title="Firecrawl not configured",
                text="Firecrawl API key is not configured.",
                metadata={"status": "unavailable"},
            )
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.firecrawl.dev/v2/scrape",
                headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload)
        return _firecrawl_page_from_payload(data, url)

    async def batch_extract_urls(self, urls: list[str]) -> ExtractionJobResult:
        urls = list(dict.fromkeys([url for url in urls if url.startswith("http")]))[: self.settings.firecrawl_max_sources_per_run]
        if not urls:
            return ExtractionJobResult(provider=self.name, status="skipped", pages=[], error="No HTTP URLs supplied.")
        if not self.settings.firecrawl_api_key:
            return ExtractionJobResult(provider=self.name, status="unavailable", pages=[], error="Firecrawl API key is not configured.")

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                started = await client.post(
                    "https://api.firecrawl.dev/v2/batch/scrape",
                    headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                    json={"urls": urls, "formats": ["markdown"], "onlyMainContent": True},
                )
                started.raise_for_status()
                payload = started.json()
                job_id = payload.get("id") or payload.get("jobId") or payload.get("data", {}).get("id")
                if not job_id:
                    data = payload.get("data") if isinstance(payload.get("data"), list) else []
                    pages = [_firecrawl_page_from_payload(item, urls[0]) for item in data]
                    return ExtractionJobResult(provider=self.name, status="completed", pages=pages)

                deadline = self.settings.firecrawl_wait_timeout_seconds
                elapsed = 0
                status_payload: dict[str, Any] = {}
                while elapsed <= deadline:
                    await asyncio.sleep(max(1, self.settings.firecrawl_poll_interval_seconds))
                    elapsed += max(1, self.settings.firecrawl_poll_interval_seconds)
                    status_response = await client.get(
                        f"https://api.firecrawl.dev/v2/batch/scrape/{job_id}",
                        headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                    )
                    status_response.raise_for_status()
                    status_payload = status_response.json()
                    status = status_payload.get("status")
                    if status in {"completed", "failed", "cancelled"}:
                        break

                pages = [_firecrawl_page_from_payload(item, urls[0]) for item in status_payload.get("data", []) or []]
                status = status_payload.get("status") or "timeout"
                return ExtractionJobResult(provider=self.name, status=status, pages=pages, job_id=str(job_id))
        except Exception as exc:
            pages = await self._fallback_scrape_many(urls)
            return ExtractionJobResult(
                provider=self.name,
                status="fallback_completed" if pages else "failed",
                pages=pages,
                error=str(exc),
            )

    async def crawl_url(self, url: str, *, limit: int = 8, max_depth: int = 1) -> ExtractionJobResult:
        if not url.startswith("http"):
            return ExtractionJobResult(provider=self.name, status="skipped", pages=[], error="No HTTP URL supplied.")
        if not self.settings.firecrawl_api_key:
            return ExtractionJobResult(provider=self.name, status="unavailable", pages=[], error="Firecrawl API key is not configured.")

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                started = await client.post(
                    "https://api.firecrawl.dev/v2/crawl",
                    headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                    json={
                        "url": url,
                        "limit": limit,
                        "maxDepth": max_depth,
                        "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
                    },
                )
                started.raise_for_status()
                payload = started.json()
                job_id = payload.get("id") or payload.get("jobId") or payload.get("data", {}).get("id")
                if not job_id:
                    return ExtractionJobResult(provider=self.name, status="failed", pages=[], error="Firecrawl crawl did not return a job id.")

                elapsed = 0
                status_payload: dict[str, Any] = {}
                while elapsed <= self.settings.firecrawl_wait_timeout_seconds:
                    await asyncio.sleep(max(1, self.settings.firecrawl_poll_interval_seconds))
                    elapsed += max(1, self.settings.firecrawl_poll_interval_seconds)
                    status_response = await client.get(
                        f"https://api.firecrawl.dev/v2/crawl/{job_id}",
                        headers={"Authorization": f"Bearer {self.settings.firecrawl_api_key}"},
                    )
                    status_response.raise_for_status()
                    status_payload = status_response.json()
                    if status_payload.get("status") in {"completed", "failed", "cancelled"}:
                        break

                pages = [_firecrawl_page_from_payload(item, url) for item in status_payload.get("data", []) or []]
                return ExtractionJobResult(
                    provider=self.name,
                    status=status_payload.get("status") or "timeout",
                    pages=pages,
                    job_id=str(job_id),
                )
        except Exception as exc:
            page = await self.extract_url(url)
            return ExtractionJobResult(provider=self.name, status="fallback_completed", pages=[page] if page.text else [], error=str(exc))

    async def _fallback_scrape_many(self, urls: list[str]) -> list[ExtractedPage]:
        semaphore = asyncio.Semaphore(max(1, self.settings.firecrawl_concurrency))

        async def scrape(url: str) -> ExtractedPage | None:
            async with semaphore:
                try:
                    page = await self.extract_url(url)
                    return page if page.text else None
                except Exception:
                    return None

        pages = await asyncio.gather(*(scrape(url) for url in urls))
        return [page for page in pages if page is not None]


class ApifyExtractionProvider(ExtractionProvider):
    name = "apify"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def extract_url(self, url: str) -> ExtractedPage:
        result = await self.crawl_urls([url])
        if result.pages:
            return result.pages[0]
        return ExtractedPage(url=url, title="Apify extraction unavailable", text=result.error or "", metadata={"status": result.status})

    async def crawl_urls(self, urls: list[str]) -> ExtractionJobResult:
        urls = list(dict.fromkeys([url for url in urls if url.startswith("http")]))[: self.settings.apify_max_crawl_pages]
        if not urls:
            return ExtractionJobResult(provider=self.name, status="skipped", pages=[], error="No HTTP URLs supplied.")
        if not self.settings.apify_api_token:
            return ExtractionJobResult(provider=self.name, status="unavailable", pages=[], error="Apify API token is not configured.")

        actor_id = self.settings.apify_actor_id.replace("/", "~")
        run_input = {
            "startUrls": [{"url": url} for url in urls],
            "maxCrawlPages": self.settings.apify_max_crawl_pages,
            "maxCrawlDepth": 1,
        }
        try:
            async with httpx.AsyncClient(timeout=max(60, self.settings.apify_wait_timeout_seconds + 30)) as client:
                run_response = await client.post(
                    f"https://api.apify.com/v2/acts/{actor_id}/runs",
                    params={"token": self.settings.apify_api_token, "waitForFinish": self.settings.apify_wait_timeout_seconds},
                    json=run_input,
                )
                run_response.raise_for_status()
                run_payload = run_response.json().get("data", run_response.json())
                run_id = run_payload.get("id")
                status = run_payload.get("status", "unknown")
                dataset_id = run_payload.get("defaultDatasetId")

                if run_id and status not in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                    poll_response = await client.get(
                        f"https://api.apify.com/v2/actor-runs/{run_id}",
                        params={"token": self.settings.apify_api_token, "waitForFinish": self.settings.apify_wait_timeout_seconds},
                    )
                    poll_response.raise_for_status()
                    run_payload = poll_response.json().get("data", poll_response.json())
                    status = run_payload.get("status", status)
                    dataset_id = run_payload.get("defaultDatasetId", dataset_id)

                if not dataset_id:
                    return ExtractionJobResult(provider=self.name, status=status, pages=[], job_id=run_id, error="Apify run did not return a dataset id.")

                dataset_response = await client.get(
                    f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                    params={
                        "token": self.settings.apify_api_token,
                        "format": "json",
                        "clean": "1",
                        "limit": self.settings.apify_dataset_item_limit,
                    },
                )
                dataset_response.raise_for_status()
                items = dataset_response.json()
                pages = [
                    _apify_page_from_item(item, urls[0])
                    for item in items
                    if isinstance(item, dict)
                ]
                return ExtractionJobResult(provider=self.name, status=status, pages=pages, job_id=run_id)
        except Exception as exc:
            return ExtractionJobResult(provider=self.name, status="failed", pages=[], error=str(exc))
