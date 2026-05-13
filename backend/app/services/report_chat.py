from __future__ import annotations

import asyncio
import json
from typing import Any

from openai import OpenAI

from app.config import Settings
from app.models import DrilldownRun, ResearchRun
from app.storage.evidence_store import EvidenceTableStore


def _source_numbers(run: ResearchRun) -> dict[str, int]:
    if not run.report:
        return {}
    public_sources = [source for source in run.report.sources if source.url.startswith("http")]
    return {source.id: index + 1 for index, source in enumerate(public_sources)}


def _source_labels(source_ids: list[str], source_numbers: dict[str, int], limit: int = 5) -> list[str]:
    labels = [f"S{source_numbers[source_id]}" for source_id in source_ids if source_id in source_numbers]
    if not labels:
        return ["Evidence pack"]
    return labels[:limit]


def _row_payload(row: dict[str, Any], source_numbers: dict[str, int]) -> dict[str, Any]:
    return {
        "row_id": row["row_id"],
        "table_name": row["table_name"],
        "row_type": row["row_type"],
        "section_id": row.get("section_id"),
        "title": row["title"],
        "detail": row["detail"],
        "source_labels": _source_labels(row.get("source_ids", []), source_numbers),
        "source_ids": row.get("source_ids", []),
        "confidence_score": row.get("confidence_score", 0),
        "retrieval_scores": {
            "hybrid": row.get("hybrid_score"),
            "semantic": row.get("semantic_score"),
            "keyword": row.get("search_score"),
        },
        "normalized_fields": row.get("normalized_fields", {}),
    }


def _row_embedding_text(row: dict[str, Any]) -> str:
    normalized_fields = row.get("normalized_fields", {})
    normalized_text = json.dumps(normalized_fields, ensure_ascii=False, sort_keys=True) if normalized_fields else ""
    return "\n".join(
        value
        for value in [
            f"Table: {row.get('table_name', '')}",
            f"Type: {row.get('row_type', '')}",
            f"Section: {row.get('section_id') or ''}",
            f"Title: {row.get('title', '')}",
            f"Detail: {row.get('detail', '')}",
            f"Fields: {normalized_text[:1200]}",
        ]
        if value.strip()
    )[:6000]


class ReportChatService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def retrieve(
        self,
        *,
        run: ResearchRun,
        question: str,
        evidence_store: EvidenceTableStore,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        analytics = evidence_store.analytics_snapshot(run.id, question)
        if not (self.settings.openai_api_key and self.settings.allow_live_providers):
            return evidence_store.hybrid_search_rows(run.id, question, limit=limit), analytics, "evidence_mart_keyword_sql"

        model = self.settings.openai_embedding_model
        dimensions = self.settings.openai_embedding_dimensions
        rows_to_embed = evidence_store.rows_needing_embeddings(
            run.id,
            model=model,
            dimensions=dimensions,
            limit=self.settings.report_chat_embedding_max_rows,
        )
        try:
            if rows_to_embed:
                await self._embed_missing_rows(evidence_store, run.id, rows_to_embed, model=model, dimensions=dimensions)
            query_embedding = (await self._embed_texts([question], model=model, dimensions=dimensions))[0]
            return (
                evidence_store.hybrid_search_rows(
                    run.id,
                    question,
                    query_embedding=query_embedding,
                    model=model,
                    dimensions=dimensions,
                    limit=limit,
                ),
                analytics,
                "evidence_mart_sql_plus_openai_embeddings",
            )
        except Exception as exc:
            analytics["embedding_fallback"] = str(exc)
            return evidence_store.hybrid_search_rows(run.id, question, limit=limit), analytics, "evidence_mart_keyword_sql_embedding_fallback"

    async def answer(
        self,
        *,
        run: ResearchRun,
        question: str,
        evidence_rows: list[dict[str, Any]],
        analytics: dict[str, Any] | None = None,
        retrieval_mode: str = "duckdb_keyword_sql",
    ) -> DrilldownRun:
        source_numbers = _source_numbers(run)
        payload_rows = [_row_payload(row, source_numbers) for row in evidence_rows]
        source_ids = list(dict.fromkeys(source_id for row in payload_rows for source_id in row["source_ids"]))
        analytics = analytics or {}
        if not payload_rows:
            return DrilldownRun(
                parent_run_id=run.id,
                question=question,
                answer="I could not find relevant evidence rows for this question in the generated report. Please run a drilldown research job if new evidence is needed.",
                source_ids=[],
                evidence_rows=[],
                analytics=analytics,
                retrieval_mode=retrieval_mode,
                model=None,
                provider="duckdb_retrieval",
            )
        if not (self.settings.openai_api_key and self.settings.allow_live_providers):
            answer_lines = [
                "Live GPT answering is disabled, so this is a retrieval-only answer from the evidence mart and SQL summaries.",
                "Most relevant evidence:",
            ]
            for row in payload_rows[:6]:
                answer_lines.append(f"- {row['title']} ({', '.join(row['source_labels'])})")
            relevant_counts = analytics.get("relevant_table_counts") or analytics.get("table_counts") or []
            if relevant_counts:
                answer_lines.append("Relevant table mix:")
                for item in relevant_counts[:5]:
                    answer_lines.append(f"- {item['table_name']}: {item['row_count']} rows, avg confidence {item['avg_confidence']}")
            return DrilldownRun(
                parent_run_id=run.id,
                question=question,
                answer="\n".join(answer_lines),
                source_ids=source_ids,
                evidence_rows=payload_rows[:12],
                analytics=analytics,
                retrieval_mode=retrieval_mode,
                model=None,
                provider="evidence_mart_retrieval",
            )

        client = OpenAI(api_key=self.settings.openai_api_key, timeout=max(60, self.settings.openai_synthesis_timeout_seconds))
        model = self.settings.openai_extraction_model
        response = await asyncio.to_thread(
            client.responses.create,
            model=model,
            reasoning={"effort": "medium"},
            instructions=(
                "You answer questions about a generated account-intelligence report. "
                "Use only the provided evidence rows and SQL analytical summaries. Do not use outside knowledge or web browsing. "
                "If the evidence rows do not answer the question, say that the report evidence does not contain it. "
                "Use table counts and signal/source-tier mixes for analytical/count questions, and use evidence rows for factual support. "
                "Cite evidence using the provided source_labels such as S3 or S10, and mention confidence or directionality when useful. "
                "Keep the answer concise but useful for an account team."
            ),
            input=json.dumps(
                {
                    "company_name": run.company_name,
                    "question": question,
                    "retrieval_mode": retrieval_mode,
                    "duckdb_analytics": analytics,
                    "evidence_rows": payload_rows[:24],
                },
                ensure_ascii=False,
            ),
            max_output_tokens=1800,
        )
        return DrilldownRun(
            parent_run_id=run.id,
            question=question,
            answer=response.output_text or "No answer returned by the model.",
            source_ids=source_ids,
            evidence_rows=payload_rows[:12],
            analytics=analytics,
            retrieval_mode=retrieval_mode,
            model=model,
            provider="openai_responses_duckdb_hybrid_chat",
        )

    async def _embed_missing_rows(
        self,
        evidence_store: EvidenceTableStore,
        run_id: str,
        rows: list[dict[str, Any]],
        *,
        model: str,
        dimensions: int,
    ) -> None:
        batch_size = max(1, min(self.settings.report_chat_embedding_batch_size, 256))
        for index in range(0, len(rows), batch_size):
            batch = rows[index : index + batch_size]
            vectors = await self._embed_texts([_row_embedding_text(row) for row in batch], model=model, dimensions=dimensions)
            evidence_store.upsert_embeddings(
                run_id,
                embeddings_by_row_id={row["row_id"]: vector for row, vector in zip(batch, vectors)},
                model=model,
                dimensions=dimensions,
            )

    async def _embed_texts(self, texts: list[str], *, model: str, dimensions: int) -> list[list[float]]:
        client = OpenAI(api_key=self.settings.openai_api_key, timeout=max(60, self.settings.openai_synthesis_timeout_seconds))

        def _call() -> Any:
            return client.embeddings.create(
                model=model,
                input=texts,
                dimensions=dimensions,
                encoding_format="float",
            )

        response = await asyncio.to_thread(_call)
        return [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]
