from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    publisher: str | None = None
    published_at: str | None = None


@dataclass(frozen=True)
class ExtractedPage:
    url: str
    title: str
    text: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class ExtractionJobResult:
    provider: str
    status: str
    pages: list[ExtractedPage]
    job_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SynthesisClaim:
    text: str
    claim_type: str
    source_ids: list[str]
    confidence_score: float


@dataclass(frozen=True)
class SynthesisResult:
    summary: str
    bullets: list[str]
    claims: list[SynthesisClaim]
    confidence_score: float
    status: str
    provider: str
    raw_response_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class DeepResearchResult:
    output_text: str
    sources: list[SearchResult]
    provider: str
    status: str
    response_id: str | None = None
    tool_call_count: int = 0
    error: str | None = None


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, allowed_domains: list[str] | None = None) -> list[SearchResult]:
        ...


class DeepResearchProvider(Protocol):
    name: str

    async def research(self, prompt: str) -> DeepResearchResult:
        ...


class ExtractionProvider(Protocol):
    name: str

    async def extract_url(self, url: str) -> ExtractedPage:
        ...


class PresentationProvider(Protocol):
    name: str

    async def render(self, *args, **kwargs):
        ...


class SynthesisProvider(Protocol):
    name: str

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
        ...
