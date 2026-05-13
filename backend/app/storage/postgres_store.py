from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import Settings
from app.models import AccountReport, EvidenceTableRow, ResearchRun


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class PostgresEvidenceTableStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.path = "postgresql://evidence_rows"
        self._ensure_schema()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_rows (
                    run_id TEXT NOT NULL,
                    row_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    row_type TEXT NOT NULL,
                    section_id TEXT,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    normalized_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
                    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    snapshot_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    claim_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    signal_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    extracted_value_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    source_tier TEXT,
                    signal_type TEXT,
                    confidence_score DOUBLE PRECISION NOT NULL,
                    include_in_analysis BOOLEAN NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    embedding_model TEXT,
                    embedding_dimensions INTEGER,
                    embedding_json JSONB,
                    embedding_updated_at TIMESTAMPTZ,
                    PRIMARY KEY (run_id, row_id)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_rows_run_table ON evidence_rows(run_id, table_name)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_rows_run_include ON evidence_rows(run_id, include_in_analysis)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_rows_signal ON evidence_rows(run_id, signal_type)")
            connection.commit()

    def replace_report_rows(self, report: AccountReport) -> None:
        with self._connect() as connection:
            existing_embedding_rows = connection.execute(
                """
                SELECT row_id, embedding_model, embedding_dimensions, embedding_json, embedding_updated_at
                FROM evidence_rows
                WHERE run_id = %s
                """,
                (report.run_id,),
            ).fetchall()
            existing_embeddings = {row["row_id"]: row for row in existing_embedding_rows}
            connection.execute("DELETE FROM evidence_rows WHERE run_id = %s", (report.run_id,))
            rows = [self._row_tuple(report.run_id, row, existing_embeddings.get(row.id)) for row in report.evidence_table_rows]
            if rows:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO evidence_rows (
                            run_id, row_id, table_name, row_type, section_id, title, detail,
                            normalized_fields, source_ids, snapshot_ids, claim_ids,
                            signal_ids, extracted_value_ids, source_tier, signal_type,
                            confidence_score, include_in_analysis, created_at,
                            embedding_model, embedding_dimensions, embedding_json, embedding_updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        rows,
                    )
            connection.commit()

    def delete_run(self, run_id: str) -> int:
        with self._connect() as connection:
            deleted_count = connection.execute("SELECT COUNT(*) AS count FROM evidence_rows WHERE run_id = %s", (run_id,)).fetchone()["count"]
            connection.execute("DELETE FROM evidence_rows WHERE run_id = %s", (run_id,))
            connection.commit()
        return int(deleted_count)

    def table_counts(self, run_id: str) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT table_name, COUNT(*) AS count FROM evidence_rows WHERE run_id = %s GROUP BY table_name ORDER BY COUNT(*) DESC",
                (run_id,),
            ).fetchall()
        return {row["table_name"]: row["count"] for row in rows}

    def analytics_snapshot(self, run_id: str, question: str | None = None) -> dict[str, Any]:
        terms = self._search_terms(question or "")
        with self._connect() as connection:
            table_counts = connection.execute(
                """
                SELECT table_name, COUNT(*) AS row_count, AVG(confidence_score) AS avg_confidence
                FROM evidence_rows
                WHERE run_id = %s AND include_in_analysis = TRUE
                GROUP BY table_name
                ORDER BY row_count DESC, avg_confidence DESC
                LIMIT 24
                """,
                (run_id,),
            ).fetchall()
            source_tier_mix = connection.execute(
                """
                SELECT COALESCE(source_tier, 'unclassified') AS source_tier, COUNT(*) AS row_count, AVG(confidence_score) AS avg_confidence
                FROM evidence_rows
                WHERE run_id = %s AND include_in_analysis = TRUE
                GROUP BY source_tier
                ORDER BY row_count DESC
                LIMIT 12
                """,
                (run_id,),
            ).fetchall()
            signal_type_mix = connection.execute(
                """
                SELECT COALESCE(signal_type, 'unclassified') AS signal_type, COUNT(*) AS row_count, AVG(confidence_score) AS avg_confidence
                FROM evidence_rows
                WHERE run_id = %s AND include_in_analysis = TRUE
                GROUP BY signal_type
                ORDER BY row_count DESC, avg_confidence DESC
                LIMIT 18
                """,
                (run_id,),
            ).fetchall()
            top_confidence_rows = connection.execute(
                """
                SELECT row_id, table_name, row_type, title, confidence_score
                FROM evidence_rows
                WHERE run_id = %s AND include_in_analysis = TRUE
                ORDER BY confidence_score DESC, table_name, title
                LIMIT 12
                """,
                (run_id,),
            ).fetchall()
            relevant_table_counts: list[dict[str, Any]] = []
            if terms:
                where_sql, params = self._term_where_clause(terms)
                relevant_table_counts = connection.execute(
                    f"""
                    SELECT table_name, COUNT(*) AS row_count, AVG(confidence_score) AS avg_confidence
                    FROM evidence_rows
                    WHERE run_id = %s AND include_in_analysis = TRUE AND ({where_sql})
                    GROUP BY table_name
                    ORDER BY row_count DESC, avg_confidence DESC
                    LIMIT 18
                    """,
                    [run_id, *params],
                ).fetchall()
        return {
            "table_counts": [
                {"table_name": row["table_name"], "row_count": row["row_count"], "avg_confidence": round(float(row["avg_confidence"] or 0), 3)}
                for row in table_counts
            ],
            "relevant_table_counts": [
                {"table_name": row["table_name"], "row_count": row["row_count"], "avg_confidence": round(float(row["avg_confidence"] or 0), 3)}
                for row in relevant_table_counts
            ],
            "source_tier_mix": [
                {"source_tier": row["source_tier"], "row_count": row["row_count"], "avg_confidence": round(float(row["avg_confidence"] or 0), 3)}
                for row in source_tier_mix
            ],
            "signal_type_mix": [
                {"signal_type": row["signal_type"], "row_count": row["row_count"], "avg_confidence": round(float(row["avg_confidence"] or 0), 3)}
                for row in signal_type_mix
            ],
            "top_confidence_rows": [dict(row) for row in top_confidence_rows],
        }

    def list_rows(self, run_id: str, table_name: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        params: list[Any] = [run_id]
        where = "run_id = %s"
        if table_name:
            where += " AND table_name = %s"
            params.append(table_name)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM evidence_rows
                WHERE {where}
                ORDER BY include_in_analysis DESC, confidence_score DESC, table_name, title
                LIMIT %s
                """,
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def search_rows(self, run_id: str, question: str, limit: int = 24) -> list[dict[str, Any]]:
        terms = self._search_terms(question)
        limit = max(1, min(limit, 100))
        if not terms:
            return self.list_rows(run_id, limit=limit)
        score_parts = []
        score_params: list[Any] = []
        for term in terms:
            like = f"%{term}%"
            score_parts.append("CASE WHEN lower(title) LIKE %s THEN 3 ELSE 0 END")
            score_params.append(like)
            score_parts.append("CASE WHEN lower(detail) LIKE %s THEN 1 ELSE 0 END")
            score_params.append(like)
            score_parts.append("CASE WHEN lower(table_name) LIKE %s THEN 2 ELSE 0 END")
            score_params.append(like)
        score_sql = " + ".join(score_parts)
        params = [*score_params, run_id, *score_params, limit]
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *, ({score_sql}) AS search_score
                FROM evidence_rows
                WHERE run_id = %s
                  AND include_in_analysis = TRUE
                  AND ({score_sql}) > 0
                ORDER BY search_score DESC, confidence_score DESC, table_name, title
                LIMIT %s
                """,
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def rows_needing_embeddings(self, run_id: str, *, model: str, dimensions: int, limit: int = 1500) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 5000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence_rows
                WHERE run_id = %s
                  AND include_in_analysis = TRUE
                  AND (
                    embedding_json IS NULL
                    OR embedding_model IS NULL
                    OR embedding_model != %s
                    OR embedding_dimensions IS NULL
                    OR embedding_dimensions != %s
                  )
                ORDER BY confidence_score DESC, table_name, title
                LIMIT %s
                """,
                (run_id, model, dimensions, limit),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_embeddings(self, run_id: str, *, embeddings_by_row_id: dict[str, list[float]], model: str, dimensions: int) -> None:
        if not embeddings_by_row_id:
            return
        updated_at = datetime.now(UTC)
        rows = [(model, dimensions, Jsonb(vector), updated_at, run_id, row_id) for row_id, vector in embeddings_by_row_id.items()]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    UPDATE evidence_rows
                    SET embedding_model = %s,
                        embedding_dimensions = %s,
                        embedding_json = %s,
                        embedding_updated_at = %s
                    WHERE run_id = %s AND row_id = %s
                    """,
                    rows,
                )
            connection.commit()

    def semantic_search_rows(
        self,
        run_id: str,
        *,
        query_embedding: list[float],
        model: str,
        dimensions: int,
        limit: int = 24,
        candidate_limit: int = 1200,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        candidate_limit = max(limit, min(candidate_limit, 5000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM evidence_rows
                WHERE run_id = %s
                  AND include_in_analysis = TRUE
                  AND embedding_model = %s
                  AND embedding_dimensions = %s
                  AND embedding_json IS NOT NULL
                ORDER BY confidence_score DESC, table_name, title
                LIMIT %s
                """,
                (run_id, model, dimensions, candidate_limit),
            ).fetchall()
        scored_rows: list[dict[str, Any]] = []
        for row in rows:
            payload = self._row_to_dict(row, include_embedding=True)
            embedding = payload.get("embedding")
            if not isinstance(embedding, list):
                continue
            payload["semantic_score"] = round(_cosine_similarity(query_embedding, embedding), 6)
            payload.pop("embedding", None)
            scored_rows.append(payload)
        scored_rows.sort(key=lambda row: (row.get("semantic_score", 0), row.get("confidence_score", 0)), reverse=True)
        return scored_rows[:limit]

    def hybrid_search_rows(
        self,
        run_id: str,
        question: str,
        *,
        query_embedding: list[float] | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        keyword_rows = self.search_rows(run_id, question, limit=limit * 2)
        semantic_rows: list[dict[str, Any]] = []
        if query_embedding and model and dimensions:
            semantic_rows = self.semantic_search_rows(run_id, query_embedding=query_embedding, model=model, dimensions=dimensions, limit=limit * 2)
        merged: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(keyword_rows):
            row_id = row["row_id"]
            payload = merged.setdefault(row_id, row)
            payload["keyword_rank_score"] = max(float(payload.get("keyword_rank_score", 0)), max(0.1, 1 - (index / max(1, len(keyword_rows)))))
            payload["search_score"] = max(float(payload.get("search_score", 0)), float(row.get("search_score", 0)))
        for index, row in enumerate(semantic_rows):
            row_id = row["row_id"]
            payload = merged.setdefault(row_id, row)
            payload["semantic_score"] = max(float(payload.get("semantic_score", 0)), float(row.get("semantic_score", 0)))
            payload["semantic_rank_score"] = max(float(payload.get("semantic_rank_score", 0)), max(0.1, 1 - (index / max(1, len(semantic_rows)))))
        for payload in merged.values():
            payload["hybrid_score"] = round(
                (max(0.0, float(payload.get("semantic_score", 0))) * 0.62)
                + (float(payload.get("keyword_rank_score", 0)) * 0.28)
                + (float(payload.get("confidence_score", 0)) * 0.1),
                6,
            )
        return sorted(merged.values(), key=lambda row: (row.get("hybrid_score", 0), row.get("confidence_score", 0)), reverse=True)[:limit]

    def _row_tuple(self, run_id: str, row: EvidenceTableRow, existing_embedding: dict[str, Any] | None = None) -> tuple[Any, ...]:
        existing_embedding = existing_embedding or {}
        return (
            run_id,
            row.id,
            row.table_name,
            row.row_type,
            row.section_id,
            row.title,
            row.detail,
            Jsonb(row.normalized_fields),
            Jsonb(row.source_ids),
            Jsonb(row.snapshot_ids),
            Jsonb(row.claim_ids),
            Jsonb(row.signal_ids),
            Jsonb(row.extracted_value_ids),
            row.source_tier.value if row.source_tier else None,
            row.signal_type.value if row.signal_type else None,
            row.confidence_score,
            row.include_in_analysis,
            row.created_at,
            existing_embedding.get("embedding_model"),
            existing_embedding.get("embedding_dimensions"),
            Jsonb(existing_embedding["embedding_json"]) if existing_embedding.get("embedding_json") is not None else None,
            existing_embedding.get("embedding_updated_at"),
        )

    def _row_to_dict(self, row: dict[str, Any], *, include_embedding: bool = False) -> dict[str, Any]:
        payload = dict(row)
        payload["row_id"] = payload.pop("row_id")
        payload["normalized_fields"] = payload.get("normalized_fields") or {}
        payload["source_ids"] = payload.get("source_ids") or []
        payload["snapshot_ids"] = payload.get("snapshot_ids") or []
        payload["claim_ids"] = payload.get("claim_ids") or []
        payload["signal_ids"] = payload.get("signal_ids") or []
        payload["extracted_value_ids"] = payload.get("extracted_value_ids") or []
        embedding_json = payload.pop("embedding_json", None)
        if include_embedding:
            payload["embedding"] = embedding_json if embedding_json else None
        payload["include_in_analysis"] = bool(payload["include_in_analysis"])
        return payload

    def _search_terms(self, question: str) -> list[str]:
        terms = [term.lower() for term in question.replace("&", " ").replace("/", " ").replace("?", " ").split() if len(term) >= 3]
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "into",
            "about",
            "what",
            "where",
            "when",
            "which",
            "should",
            "could",
            "would",
            "tell",
            "give",
            "show",
            "does",
            "have",
            "their",
            "there",
            "report",
            "relevant",
            "signals",
            "evidence",
        }
        return [term for term in terms if term not in stopwords][:12]

    def _term_where_clause(self, terms: list[str]) -> tuple[str, list[Any]]:
        clauses = []
        params: list[Any] = []
        for term in terms:
            like = f"%{term}%"
            clauses.append("(lower(title) LIKE %s OR lower(detail) LIKE %s OR lower(table_name) LIKE %s OR lower(COALESCE(signal_type, '')) LIKE %s)")
            params.extend([like, like, like, like])
        return " OR ".join(clauses), params


class PostgresRunStore:
    def __init__(self, settings: Settings):
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required when RUN_STORE_BACKEND=postgres")
        self.settings = settings
        self.database_url = settings.database_url
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_tables = PostgresEvidenceTableStore(self.database_url)
        self._ensure_schema()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    payload JSONB NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_research_runs_updated ON research_runs(updated_at DESC)")
            connection.commit()

    def save(self, run: ResearchRun) -> ResearchRun:
        payload = run.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO research_runs (run_id, company_name, mode, status, created_at, updated_at, completed_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    mode = EXCLUDED.mode,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    completed_at = EXCLUDED.completed_at,
                    payload = EXCLUDED.payload
                """,
                (
                    run.id,
                    run.company_name,
                    run.mode.value,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    run.completed_at,
                    Jsonb(payload),
                ),
            )
            connection.commit()
        if run.report and run.report.evidence_table_rows:
            self.evidence_tables.replace_report_rows(run.report)
        return run

    def get(self, run_id: str) -> ResearchRun | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM research_runs WHERE run_id = %s", (run_id,)).fetchone()
        if not row:
            return None
        return ResearchRun.model_validate(row["payload"])

    def list(self) -> list[ResearchRun]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM research_runs ORDER BY updated_at DESC").fetchall()
        return [ResearchRun.model_validate(row["payload"]) for row in rows]

    def delete(self, run_id: str) -> dict[str, int | bool | str]:
        with self._connect() as connection:
            row = connection.execute("SELECT run_id FROM research_runs WHERE run_id = %s", (run_id,)).fetchone()
            if not row:
                return {"deleted": False, "run_id": run_id, "evidence_rows_deleted": 0, "artifacts_deleted": 0}
            evidence_rows_deleted = self.evidence_tables.delete_run(run_id)
            connection.execute("DELETE FROM research_runs WHERE run_id = %s", (run_id,))
            connection.commit()
        return {"deleted": True, "run_id": run_id, "evidence_rows_deleted": evidence_rows_deleted, "artifacts_deleted": 0}

    def artifact_path(self, run_id: str, suffix: str) -> Path:
        run_dir = self.settings.artifacts_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / f"{run_id}.{suffix}"
