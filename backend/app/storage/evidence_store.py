from __future__ import annotations

from datetime import UTC, datetime
import json
import math
from pathlib import Path
from typing import Any

import duckdb

from app.models import AccountReport, EvidenceTableRow


class EvidenceTableStore:
    """DuckDB sidecar for queryable analytical evidence rows in local/prototype runs."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "evidence_mart.duckdb"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

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
                    normalized_fields_json TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    snapshot_ids_json TEXT NOT NULL,
                    claim_ids_json TEXT NOT NULL,
                    signal_ids_json TEXT NOT NULL,
                    extracted_value_ids_json TEXT NOT NULL,
                    source_tier TEXT,
                    signal_type TEXT,
                    confidence_score REAL NOT NULL,
                    include_in_analysis INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    embedding_model TEXT,
                    embedding_dimensions INTEGER,
                    embedding_json TEXT,
                    embedding_updated_at TEXT,
                    PRIMARY KEY (run_id, row_id)
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info('evidence_rows')").fetchall()}
            migrations = {
                "embedding_model": "ALTER TABLE evidence_rows ADD COLUMN embedding_model TEXT",
                "embedding_dimensions": "ALTER TABLE evidence_rows ADD COLUMN embedding_dimensions INTEGER",
                "embedding_json": "ALTER TABLE evidence_rows ADD COLUMN embedding_json TEXT",
                "embedding_updated_at": "ALTER TABLE evidence_rows ADD COLUMN embedding_updated_at TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)

    def replace_report_rows(self, report: AccountReport) -> None:
        with self._connect() as connection:
            existing_embedding_rows = connection.execute(
                """
                SELECT row_id, embedding_model, embedding_dimensions, embedding_json, embedding_updated_at
                FROM evidence_rows
                WHERE run_id = ?
                """,
                (report.run_id,),
            ).fetchall()
            existing_embeddings = {row[0]: row[1:] for row in existing_embedding_rows}
            connection.execute("DELETE FROM evidence_rows WHERE run_id = ?", (report.run_id,))
            rows = [self._row_tuple(report.run_id, row, existing_embeddings.get(row.id)) for row in report.evidence_table_rows]
            if rows:
                connection.executemany(
                    """
                    INSERT INTO evidence_rows (
                        run_id, row_id, table_name, row_type, section_id, title, detail,
                        normalized_fields_json, source_ids_json, snapshot_ids_json, claim_ids_json,
                        signal_ids_json, extracted_value_ids_json, source_tier, signal_type,
                        confidence_score, include_in_analysis, created_at,
                        embedding_model, embedding_dimensions, embedding_json, embedding_updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def table_counts(self, run_id: str) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT table_name, COUNT(*) FROM evidence_rows WHERE run_id = ? GROUP BY table_name ORDER BY COUNT(*) DESC",
                (run_id,),
            ).fetchall()
        return {table_name: count for table_name, count in rows}

    def analytics_snapshot(self, run_id: str, question: str | None = None) -> dict[str, Any]:
        terms = self._search_terms(question or "")
        with self._connect() as connection:
            table_counts = connection.execute(
                """
                SELECT table_name, COUNT(*) AS row_count, AVG(confidence_score) AS avg_confidence
                FROM evidence_rows
                WHERE run_id = ? AND include_in_analysis = 1
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
                WHERE run_id = ? AND include_in_analysis = 1
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
                WHERE run_id = ? AND include_in_analysis = 1
                GROUP BY signal_type
                ORDER BY row_count DESC, avg_confidence DESC
                LIMIT 18
                """,
                (run_id,),
            ).fetchall()
            top_confidence_rows_result = connection.execute(
                """
                SELECT row_id, table_name, row_type, title, confidence_score
                FROM evidence_rows
                WHERE run_id = ? AND include_in_analysis = 1
                ORDER BY confidence_score DESC, table_name, title
                LIMIT 12
                """,
                (run_id,),
            )
            top_columns = [column[0] for column in top_confidence_rows_result.description]
            top_confidence_rows = top_confidence_rows_result.fetchall()

            relevant_table_counts: list[tuple[Any, ...]] = []
            if terms:
                where_sql, params = self._term_where_clause(terms)
                relevant_table_counts = connection.execute(
                    f"""
                    SELECT table_name, COUNT(*) AS row_count, AVG(confidence_score) AS avg_confidence
                    FROM evidence_rows
                    WHERE run_id = ? AND include_in_analysis = 1 AND ({where_sql})
                    GROUP BY table_name
                    ORDER BY row_count DESC, avg_confidence DESC
                    LIMIT 18
                    """,
                    [run_id, *params],
                ).fetchall()

        return {
            "table_counts": [
                {"table_name": table_name, "row_count": count, "avg_confidence": round(float(avg or 0), 3)}
                for table_name, count, avg in table_counts
            ],
            "relevant_table_counts": [
                {"table_name": table_name, "row_count": count, "avg_confidence": round(float(avg or 0), 3)}
                for table_name, count, avg in relevant_table_counts
            ],
            "source_tier_mix": [
                {"source_tier": source_tier, "row_count": count, "avg_confidence": round(float(avg or 0), 3)}
                for source_tier, count, avg in source_tier_mix
            ],
            "signal_type_mix": [
                {"signal_type": signal_type, "row_count": count, "avg_confidence": round(float(avg or 0), 3)}
                for signal_type, count, avg in signal_type_mix
            ],
            "top_confidence_rows": [dict(zip(top_columns, row)) for row in top_confidence_rows],
        }

    def list_rows(self, run_id: str, table_name: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        params: list[Any] = [run_id]
        where = "run_id = ?"
        if table_name:
            where += " AND table_name = ?"
            params.append(table_name)
        params.append(limit)
        with self._connect() as connection:
            result = connection.execute(
                f"""
                SELECT * FROM evidence_rows
                WHERE {where}
                ORDER BY include_in_analysis DESC, confidence_score DESC, table_name, title
                LIMIT ?
                """,
                params,
            )
            columns = [column[0] for column in result.description]
            rows = result.fetchall()
        return [self._row_to_dict(dict(zip(columns, row))) for row in rows]

    def search_rows(self, run_id: str, question: str, limit: int = 24) -> list[dict[str, Any]]:
        terms = self._search_terms(question)
        limit = max(1, min(limit, 100))
        if not terms:
            return self.list_rows(run_id, limit=limit)
        score_parts = []
        score_params: list[Any] = []
        for term in terms:
            like = f"%{term}%"
            score_parts.append("CASE WHEN lower(title) LIKE ? THEN 3 ELSE 0 END")
            score_params.append(like)
            score_parts.append("CASE WHEN lower(detail) LIKE ? THEN 1 ELSE 0 END")
            score_params.append(like)
            score_parts.append("CASE WHEN lower(table_name) LIKE ? THEN 2 ELSE 0 END")
            score_params.append(like)
        score_sql = " + ".join(score_parts)
        params = [*score_params, run_id, *score_params, limit]
        with self._connect() as connection:
            result = connection.execute(
                f"""
                SELECT *, ({score_sql}) AS search_score
                FROM evidence_rows
                WHERE run_id = ?
                  AND include_in_analysis = 1
                  AND ({score_sql}) > 0
                ORDER BY search_score DESC, confidence_score DESC, table_name, title
                LIMIT ?
                """,
                params,
            )
            columns = [column[0] for column in result.description]
            rows = result.fetchall()
        return [self._row_to_dict(dict(zip(columns, row))) for row in rows]

    def rows_needing_embeddings(self, run_id: str, *, model: str, dimensions: int, limit: int = 1500) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 5000))
        with self._connect() as connection:
            result = connection.execute(
                """
                SELECT * FROM evidence_rows
                WHERE run_id = ?
                  AND include_in_analysis = 1
                  AND (
                    embedding_json IS NULL
                    OR embedding_model IS NULL
                    OR embedding_model != ?
                    OR embedding_dimensions IS NULL
                    OR embedding_dimensions != ?
                  )
                ORDER BY confidence_score DESC, table_name, title
                LIMIT ?
                """,
                (run_id, model, dimensions, limit),
            )
            columns = [column[0] for column in result.description]
            rows = result.fetchall()
        return [self._row_to_dict(dict(zip(columns, row))) for row in rows]

    def upsert_embeddings(
        self,
        run_id: str,
        *,
        embeddings_by_row_id: dict[str, list[float]],
        model: str,
        dimensions: int,
    ) -> None:
        if not embeddings_by_row_id:
            return
        updated_at = datetime.now(UTC).isoformat()
        rows = [
            (model, dimensions, json.dumps(vector), updated_at, run_id, row_id)
            for row_id, vector in embeddings_by_row_id.items()
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                UPDATE evidence_rows
                SET embedding_model = ?,
                    embedding_dimensions = ?,
                    embedding_json = ?,
                    embedding_updated_at = ?
                WHERE run_id = ? AND row_id = ?
                """,
                rows,
            )

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
            result = connection.execute(
                """
                SELECT * FROM evidence_rows
                WHERE run_id = ?
                  AND include_in_analysis = 1
                  AND embedding_model = ?
                  AND embedding_dimensions = ?
                  AND embedding_json IS NOT NULL
                ORDER BY confidence_score DESC, table_name, title
                LIMIT ?
                """,
                (run_id, model, dimensions, candidate_limit),
            )
            columns = [column[0] for column in result.description]
            rows = result.fetchall()
        scored_rows: list[dict[str, Any]] = []
        for row in rows:
            payload = self._row_to_dict(dict(zip(columns, row)), include_embedding=True)
            embedding = payload.get("embedding")
            if not isinstance(embedding, list):
                continue
            similarity = _cosine_similarity(query_embedding, embedding)
            payload["semantic_score"] = round(similarity, 6)
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
            semantic_rows = self.semantic_search_rows(
                run_id,
                query_embedding=query_embedding,
                model=model,
                dimensions=dimensions,
                limit=limit * 2,
            )

        merged: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(keyword_rows):
            row_id = row["row_id"]
            payload = merged.setdefault(row_id, row)
            keyword_score = float(row.get("search_score", 0))
            payload["keyword_rank_score"] = max(float(payload.get("keyword_rank_score", 0)), max(0.1, 1 - (index / max(1, len(keyword_rows)))))
            payload["search_score"] = max(float(payload.get("search_score", 0)), keyword_score)
        for index, row in enumerate(semantic_rows):
            row_id = row["row_id"]
            payload = merged.setdefault(row_id, row)
            payload["semantic_score"] = max(float(payload.get("semantic_score", 0)), float(row.get("semantic_score", 0)))
            payload["semantic_rank_score"] = max(float(payload.get("semantic_rank_score", 0)), max(0.1, 1 - (index / max(1, len(semantic_rows)))))

        for payload in merged.values():
            semantic_score = max(0.0, float(payload.get("semantic_score", 0)))
            keyword_rank_score = float(payload.get("keyword_rank_score", 0))
            confidence_score = float(payload.get("confidence_score", 0))
            payload["hybrid_score"] = round((semantic_score * 0.62) + (keyword_rank_score * 0.28) + (confidence_score * 0.1), 6)
        return sorted(
            merged.values(),
            key=lambda row: (row.get("hybrid_score", 0), row.get("confidence_score", 0)),
            reverse=True,
        )[:limit]

    def _row_tuple(
        self,
        run_id: str,
        row: EvidenceTableRow,
        existing_embedding: tuple[Any, ...] | None = None,
    ) -> tuple[Any, ...]:
        embedding_model, embedding_dimensions, embedding_json, embedding_updated_at = existing_embedding or (None, None, None, None)
        return (
            run_id,
            row.id,
            row.table_name,
            row.row_type,
            row.section_id,
            row.title,
            row.detail,
            json.dumps(row.normalized_fields, default=str),
            json.dumps(row.source_ids),
            json.dumps(row.snapshot_ids),
            json.dumps(row.claim_ids),
            json.dumps(row.signal_ids),
            json.dumps(row.extracted_value_ids),
            row.source_tier.value if row.source_tier else None,
            row.signal_type.value if row.signal_type else None,
            row.confidence_score,
            1 if row.include_in_analysis else 0,
            row.created_at.isoformat(),
            embedding_model,
            embedding_dimensions,
            embedding_json,
            embedding_updated_at,
        )

    def _row_to_dict(self, row: dict[str, Any], *, include_embedding: bool = False) -> dict[str, Any]:
        payload = dict(row)
        for key in (
            "normalized_fields_json",
            "source_ids_json",
            "snapshot_ids_json",
            "claim_ids_json",
            "signal_ids_json",
            "extracted_value_ids_json",
        ):
            payload[key.removesuffix("_json")] = json.loads(payload.pop(key))
        embedding_json = payload.pop("embedding_json", None)
        if include_embedding:
            payload["embedding"] = json.loads(embedding_json) if embedding_json else None
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
            clauses.append("(lower(title) LIKE ? OR lower(detail) LIKE ? OR lower(table_name) LIKE ? OR lower(COALESCE(signal_type, '')) LIKE ?)")
            params.extend([like, like, like, like])
        return " OR ".join(clauses), params


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
