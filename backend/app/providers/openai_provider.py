from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from openai import OpenAI

from app.config import Settings
from app.providers.base import (
    DeepResearchProvider,
    DeepResearchResult,
    SearchProvider,
    SearchResult,
    SynthesisClaim,
    SynthesisProvider,
    SynthesisResult,
)


class MockSearchProvider(SearchProvider):
    name = "mock_search"

    async def search(self, query: str, *, allowed_domains: list[str] | None = None) -> list[SearchResult]:
        await asyncio.sleep(0)
        return [
            SearchResult(
                title="Live provider not configured",
                url="system://live-provider-not-configured",
                snippet=(
                    "No live search key is configured. The scaffold returns unavailable fields "
                    "instead of inventing unsupported facts."
                ),
                publisher="Market Research Portal",
            )
        ]


class MockSynthesisProvider(SynthesisProvider):
    name = "mock_synthesis"

    async def synthesize_section(
        self,
        *,
        company_name: str,
        section_id: str,
        section_title: str,
        agent_name: str,
        model: str,
        reasoning_effort: str,
        evidence: list[dict],
        instructions: str,
    ) -> SynthesisResult:
        await asyncio.sleep(0)
        return SynthesisResult(
            summary=f"{section_title} synthesis is ready for live provider execution.",
            bullets=["Live synthesis provider is disabled; scaffold content remains fail-closed."],
            claims=[],
            confidence_score=0.8,
            status="partial",
            provider=self.name,
        )


class MockDeepResearchProvider(DeepResearchProvider):
    name = "mock_deep_research"

    async def research(self, prompt: str) -> DeepResearchResult:
        await asyncio.sleep(0)
        return DeepResearchResult(
            output_text=(
                "Deep Research provider is disabled in this environment. "
                "The portal will retain fail-closed unavailable fields rather than inventing facts."
            ),
            sources=[],
            provider=self.name,
            status="mocked",
        )


class OpenAISearchProvider(SearchProvider):
    name = "openai_web_search"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=max(30, settings.openai_search_timeout_seconds))

    async def search(self, query: str, *, allowed_domains: list[str] | None = None) -> list[SearchResult]:
        def _call() -> Any:
            tool: dict[str, Any] = {"type": "web_search"}
            if allowed_domains:
                tool["filters"] = {"allowed_domains": allowed_domains}
            return self.client.responses.create(
                model=self.settings.openai_extraction_model,
                reasoning={"effort": self.settings.openai_search_reasoning_effort},
                tools=[tool],
                include=["web_search_call.action.sources"],
                input=(
                    "Find the highest-credibility public sources for account-intelligence research. "
                    "Prefer official company pages, investor relations, annual/quarterly reports, earnings materials, press releases/newsroom pages, "
                    "reputable business/technology news, official partner/customer announcements, and official careers/job pages. "
                    f"Research query: {query}"
                ),
            )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_call),
                timeout=max(30, self.settings.openai_search_timeout_seconds),
            )
        except Exception as exc:
            return [
                SearchResult(
                    title="OpenAI live search failed",
                    url="system://openai-search-error",
                    snippet=str(exc),
                    publisher="OpenAI adapter",
                )
            ]
        results: list[SearchResult] = []

        for item in getattr(response, "output", []) or []:
            action = getattr(item, "action", None)
            sources = getattr(action, "sources", None) if action else None
            for source in sources or []:
                url = getattr(source, "url", None)
                title = getattr(source, "title", None) or url
                if url:
                    results.append(SearchResult(title=title, url=url, snippet=title))

        if not results:
            text = getattr(response, "output_text", "") or ""
            results.append(SearchResult(title="OpenAI web search response", url="system://openai-response", snippet=text))

        return results


def _extract_sources_from_response(response: Any) -> tuple[list[SearchResult], int]:
    results: list[SearchResult] = []
    tool_call_count = 0
    seen_urls: set[str] = set()

    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", None)
        if item_type and item_type.endswith("_call"):
            tool_call_count += 1

        action = getattr(item, "action", None)
        sources = getattr(action, "sources", None) if action else None
        for source in sources or []:
            url = getattr(source, "url", None)
            title = getattr(source, "title", None) or url
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(SearchResult(title=title, url=url, snippet=title))

        for content in getattr(item, "content", []) or []:
            annotations = getattr(content, "annotations", []) or []
            for annotation in annotations:
                url = getattr(annotation, "url", None)
                title = getattr(annotation, "title", None) or url
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(SearchResult(title=title, url=url, snippet=title))

    return results, tool_call_count


class OpenAIDeepResearchProvider(DeepResearchProvider):
    name = "openai_deep_research"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_deep_research_timeout_seconds)

    async def research(self, prompt: str) -> DeepResearchResult:
        def _run() -> DeepResearchResult:
            try:
                response = self.client.responses.create(
                    model=self.settings.openai_deep_research_model,
                    input=prompt,
                    background=True,
                    reasoning={"summary": "auto"},
                    tools=[{"type": "web_search_preview"}],
                    max_tool_calls=self.settings.openai_deep_research_max_tool_calls,
                    include=["web_search_call.action.sources"],
                    metadata={"workflow": "hcltech_market_research_deep_dive"},
                )
                started = time.monotonic()
                terminal_statuses = {"completed", "failed", "cancelled", "incomplete"}
                while getattr(response, "status", None) not in terminal_statuses:
                    if time.monotonic() - started > self.settings.openai_deep_research_timeout_seconds:
                        return DeepResearchResult(
                            output_text=getattr(response, "output_text", "") or "",
                            sources=[],
                            provider=self.name,
                            status="timeout",
                            response_id=getattr(response, "id", None),
                            error="OpenAI Deep Research polling timed out.",
                        )
                    time.sleep(max(1, self.settings.openai_deep_research_poll_interval_seconds))
                    response = self.client.responses.retrieve(
                        response.id,
                        include=["web_search_call.action.sources"],
                    )

                sources, tool_call_count = _extract_sources_from_response(response)
                error = getattr(response, "error", None)
                return DeepResearchResult(
                    output_text=getattr(response, "output_text", "") or "",
                    sources=sources,
                    provider=self.name,
                    status=getattr(response, "status", "unknown") or "unknown",
                    response_id=getattr(response, "id", None),
                    tool_call_count=tool_call_count,
                    error=str(error) if error else None,
                )
            except Exception as exc:
                return DeepResearchResult(
                    output_text="",
                    sources=[],
                    provider=self.name,
                    status="failed",
                    error=str(exc),
                )

        return await asyncio.to_thread(_run)


SECTION_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "claim_type": {"type": "string", "enum": ["fact", "inference", "recommendation", "unavailable"]},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence_score": {"type": "number"},
                },
                "required": ["text", "claim_type", "source_ids", "confidence_score"],
            },
        },
        "confidence_score": {"type": "number"},
        "status": {"type": "string", "enum": ["complete", "partial", "unavailable"]},
    },
    "required": ["summary", "bullets", "claims", "confidence_score", "status"],
}


class OpenAISynthesisProvider(SynthesisProvider):
    name = "openai_responses_synthesis"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=max(60, settings.openai_synthesis_timeout_seconds))

    async def synthesize_section(
        self,
        *,
        company_name: str,
        section_id: str,
        section_title: str,
        agent_name: str,
        model: str,
        reasoning_effort: str,
        evidence: list[dict],
        instructions: str,
    ) -> SynthesisResult:
        evidence_limit = max(20, self.settings.openai_synthesis_evidence_limit)
        evidence_records = evidence[:evidence_limit]
        allowed_source_ids = {str(item.get("id")) for item in evidence_records}
        payload = {
            "company_name": company_name,
            "section_id": section_id,
            "section_title": section_title,
            "agent_name": agent_name,
            "evidence": evidence_records,
            "instructions": instructions,
            "allowed_source_ids": sorted(allowed_source_ids),
        }
        max_output_tokens = (
            self.settings.openai_synthesis_max_output_tokens
            if reasoning_effort in {"high", "xhigh"}
            else max(6000, int(self.settings.openai_synthesis_max_output_tokens * 0.7))
        )

        def _call() -> Any:
            return self.client.responses.create(
                model=model,
                reasoning={"effort": reasoning_effort},
                instructions=(
                    "You are a source-grounded market research synthesis agent. "
                    "Return JSON only. Use only the provided evidence records. "
                    "Every factual or inferential claim must cite one or more allowed source_ids. "
                    "Follow the source-tier policy in each evidence record: Tier 1 official financial/filing evidence is required for exact financial metrics; "
                    "Tier 2 official company or partner evidence can support announced partnerships, investments, product launches, customer wins, roadmap statements, and executive-stated priorities; "
                    "Tier 3 reputable external context and Tier 4 job/ecosystem signals can support directional signals but not exact spend, headcount, revenue, or deal values. "
                    "Use the language 'Exact value not disclosed' for missing numeric attributes, 'Directional signal' for cited non-numeric patterns, and 'Inferred opportunity' for recommendations derived from cited premises. "
                    "If exact numbers are missing, keep the exact number unavailable but still synthesize the supported directional signal. "
                    "If evidence is insufficient for a specific attribute, mark that attribute unavailable; do not make the whole section unavailable when other cited facts or directional signals support useful analysis. "
                    "Do not invent financial numbers, percentages, vendors, executives, or dates."
                ),
                input=json.dumps(payload, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "section_synthesis",
                        "schema": SECTION_SYNTHESIS_SCHEMA,
                        "strict": True,
                    }
                },
                max_output_tokens=max_output_tokens,
            )

        def _repair_call(raw_text: str, parse_error: str) -> Any:
            return self.client.responses.create(
                model=self.settings.openai_analysis_model,
                reasoning={"effort": "low"},
                instructions=(
                    "Repair the supplied malformed JSON into valid JSON that matches the provided schema. "
                    "Do not add new facts. Preserve the original meaning and source_ids. Return JSON only."
                ),
                input=json.dumps(
                    {
                        "malformed_json": raw_text[:14000],
                        "parse_error": parse_error,
                        "allowed_source_ids": sorted(allowed_source_ids),
                    },
                    ensure_ascii=False,
                ),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "section_synthesis",
                        "schema": SECTION_SYNTHESIS_SCHEMA,
                        "strict": True,
                    }
                },
                max_output_tokens=self.settings.openai_json_repair_max_output_tokens,
            )

        try:
            response = await asyncio.to_thread(_call)
            output_text = response.output_text or ""
            try:
                parsed = json.loads(output_text)
            except json.JSONDecodeError:
                try:
                    match = re.search(r"\{.*\}", output_text, flags=re.DOTALL)
                    if not match:
                        raise
                    parsed = json.loads(match.group(0))
                except Exception as parse_exc:
                    repaired_response = await asyncio.to_thread(_repair_call, output_text, str(parse_exc))
                    output_text = repaired_response.output_text or ""
                    parsed = json.loads(output_text)
                    response = repaired_response
            claims: list[SynthesisClaim] = []
            for item in parsed.get("claims", []):
                filtered_source_ids = [source_id for source_id in item.get("source_ids", []) if source_id in allowed_source_ids]
                if not filtered_source_ids and item.get("claim_type") != "unavailable":
                    continue
                claims.append(
                    SynthesisClaim(
                        text=item["text"],
                        claim_type=item["claim_type"],
                        source_ids=filtered_source_ids,
                        confidence_score=max(0.0, min(1.0, float(item.get("confidence_score", 0)))),
                    )
                )
            return SynthesisResult(
                summary=parsed["summary"],
                bullets=[str(bullet) for bullet in parsed.get("bullets", [])],
                claims=claims,
                confidence_score=max(0.0, min(1.0, float(parsed.get("confidence_score", 0)))),
                status=parsed.get("status", "partial"),
                provider=self.name,
                raw_response_id=getattr(response, "id", None),
            )
        except Exception as exc:
            return SynthesisResult(
                summary=f"Live synthesis failed for {section_title}; scaffold content retained.",
                bullets=[str(exc)[:300]],
                claims=[],
                confidence_score=0.0,
                status="partial",
                provider=self.name,
                error=str(exc),
            )
