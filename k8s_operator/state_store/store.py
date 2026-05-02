"""SQLite-backed persistent state store for incidents, jobs, and circuit breakers."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import structlog

from ..models import Issue


logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | str | None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


class SQLiteStateStore:
    """Durable local state store for autonomous control decisions."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    issue_id TEXT PRIMARY KEY,
                    issue_type TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    resource_name TEXT NOT NULL,
                    resource_kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    resolved_at TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS incident_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    resource_name TEXT NOT NULL,
                    resource_kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS diagnoses (
                    issue_id TEXT PRIMARY KEY,
                    root_cause TEXT,
                    analysis TEXT,
                    strategy TEXT,
                    confidence REAL,
                    reasoning TEXT,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    workflow_name TEXT,
                    priority INTEGER NOT NULL,
                    delay_seconds INTEGER NOT NULL,
                    confidence_threshold REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    issue_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    resource_name TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    workflow_name TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    run_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT,
                    payload TEXT
                );

                CREATE TABLE IF NOT EXISTS breaker_states (
                    breaker_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    failure_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    opened_until TEXT,
                    last_failure_at TEXT,
                    last_success_at TEXT,
                    updated_at TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_incidents_lookup
                    ON incidents(namespace, resource_name, issue_type, detected_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_due
                    ON jobs(status, run_at, priority);
                CREATE INDEX IF NOT EXISTS idx_jobs_lookup
                    ON jobs(namespace, resource_name, issue_type, status, updated_at);
                """
            )
            connection.commit()
        logger.info("state_store_initialized", path=str(self.db_path))

    async def record_incident(self, issue: Issue, status: str = "open", metadata: Optional[Dict[str, Any]] = None) -> None:
        await asyncio.to_thread(self._record_incident_sync, issue, status, metadata or {})

    def _record_incident_sync(self, issue: Issue, status: str, metadata: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents (
                    issue_id, issue_type, namespace, resource_name, resource_kind,
                    severity, status, detected_at, resolved_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(issue_id) DO UPDATE SET
                    status=excluded.status,
                    detected_at=excluded.detected_at,
                    resolved_at=excluded.resolved_at,
                    metadata=excluded.metadata
                """,
                (
                    issue.issue_id,
                    issue.issue_type.value,
                    issue.resource_namespace,
                    issue.resource_name,
                    issue.resource_kind,
                    issue.severity,
                    status,
                    _to_iso(issue.detected_at),
                    None if status == "open" else _to_iso(_utcnow()),
                    json.dumps(metadata, default=str),
                ),
            )

            connection.execute(
                """
                INSERT INTO incident_events (
                    issue_id, issue_type, namespace, resource_name, resource_kind,
                    severity, status, detected_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue.issue_id,
                    issue.issue_type.value,
                    issue.resource_namespace,
                    issue.resource_name,
                    issue.resource_kind,
                    issue.severity,
                    status,
                    _to_iso(issue.detected_at),
                    json.dumps(metadata, default=str),
                ),
            )
            connection.commit()

    async def mark_incident_resolved(self, issue_id: str) -> None:
        await asyncio.to_thread(self._mark_incident_resolved_sync, issue_id)

    def _mark_incident_resolved_sync(self, issue_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE incidents SET status='resolved', resolved_at=? WHERE issue_id=?",
                (_to_iso(_utcnow()), issue_id),
            )
            connection.commit()

    async def count_open_issues(self, namespace: Optional[str] = None) -> int:
        return await asyncio.to_thread(self._count_open_issues_sync, namespace)

    def _count_open_issues_sync(self, namespace: Optional[str]) -> int:
        query = "SELECT COUNT(*) AS count FROM incidents WHERE status='open'"
        params: List[Any] = []
        if namespace:
            query += " AND namespace=?"
            params.append(namespace)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
            return int(row["count"] if row else 0)

    async def count_recent_incidents(
        self,
        namespace: str,
        resource_name: str,
        issue_type: str,
        window_minutes: int,
    ) -> int:
        return await asyncio.to_thread(
            self._count_recent_incidents_sync,
            namespace,
            resource_name,
            issue_type,
            window_minutes,
        )

    def _count_recent_incidents_sync(
        self,
        namespace: str,
        resource_name: str,
        issue_type: str,
        window_minutes: int,
    ) -> int:
        cutoff = _to_iso(_utcnow() - timedelta(minutes=window_minutes))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM incident_events
                WHERE namespace=? AND resource_name=? AND issue_type=? AND detected_at >= ?
                """,
                (namespace, resource_name, issue_type, cutoff),
            ).fetchone()
            return int(row["count"] if row else 0)

    async def count_recent_job_failures(
        self,
        namespace: str,
        resource_name: str,
        window_minutes: int,
    ) -> int:
        return await asyncio.to_thread(
            self._count_recent_job_failures_sync,
            namespace,
            resource_name,
            window_minutes,
        )

    def _count_recent_job_failures_sync(
        self,
        namespace: str,
        resource_name: str,
        window_minutes: int,
    ) -> int:
        cutoff = _to_iso(_utcnow() - timedelta(minutes=window_minutes))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM jobs
                WHERE namespace=? AND resource_name=? AND status='failed' AND updated_at >= ?
                """,
                (namespace, resource_name, cutoff),
            ).fetchone()
            return int(row["count"] if row else 0)

    async def record_diagnosis(self, issue_id: str, diagnosis: Any) -> None:
        await asyncio.to_thread(self._record_diagnosis_sync, issue_id, diagnosis)

    def _record_diagnosis_sync(self, issue_id: str, diagnosis: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO diagnoses (
                    issue_id, root_cause, analysis, strategy, confidence,
                    reasoning, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(issue_id) DO UPDATE SET
                    root_cause=excluded.root_cause,
                    analysis=excluded.analysis,
                    strategy=excluded.strategy,
                    confidence=excluded.confidence,
                    reasoning=excluded.reasoning,
                    created_at=excluded.created_at,
                    metadata=excluded.metadata
                """,
                (
                    issue_id,
                    getattr(diagnosis, "root_cause", ""),
                    getattr(diagnosis, "analysis", ""),
                    getattr(getattr(diagnosis, "recommended_strategy", None), "value", ""),
                    float(getattr(diagnosis, "confidence", 0.0)),
                    getattr(diagnosis, "reasoning", ""),
                    _to_iso(_utcnow()),
                    json.dumps(getattr(diagnosis, "suggested_actions", []), default=str),
                ),
            )
            connection.commit()

    async def record_decision(self, issue_id: str, decision: Dict[str, Any]) -> None:
        await asyncio.to_thread(self._record_decision_sync, issue_id, decision)

    def _record_decision_sync(self, issue_id: str, decision: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decisions (
                    decision_id, issue_id, action, strategy, workflow_name,
                    priority, delay_seconds, confidence_threshold, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO UPDATE SET
                    action=excluded.action,
                    strategy=excluded.strategy,
                    workflow_name=excluded.workflow_name,
                    priority=excluded.priority,
                    delay_seconds=excluded.delay_seconds,
                    confidence_threshold=excluded.confidence_threshold,
                    created_at=excluded.created_at,
                    metadata=excluded.metadata
                """,
                (
                    decision["decision_id"],
                    issue_id,
                    decision["action"],
                    decision["strategy"],
                    decision.get("workflow_name"),
                    int(decision.get("priority", 50)),
                    int(decision.get("delay_seconds", 0)),
                    float(decision.get("confidence_threshold", 0.0)),
                    _to_iso(_utcnow()),
                    json.dumps(decision, default=str),
                ),
            )
            connection.commit()

    async def upsert_job(self, job: Dict[str, Any]) -> None:
        await asyncio.to_thread(self._upsert_job_sync, job)

    def _upsert_job_sync(self, job: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, issue_id, namespace, resource_name, issue_type,
                    workflow_name, step_index, strategy, priority, run_at,
                    attempts, max_retries, status, created_at, updated_at,
                    last_error, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    workflow_name=excluded.workflow_name,
                    step_index=excluded.step_index,
                    strategy=excluded.strategy,
                    priority=excluded.priority,
                    run_at=excluded.run_at,
                    attempts=excluded.attempts,
                    max_retries=excluded.max_retries,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    last_error=excluded.last_error,
                    payload=excluded.payload
                """,
                (
                    job["job_id"],
                    job["issue_id"],
                    job["namespace"],
                    job["resource_name"],
                    job["issue_type"],
                    job["workflow_name"],
                    int(job["step_index"]),
                    job["strategy"],
                    int(job.get("priority", 50)),
                    _to_iso(job["run_at"]),
                    int(job.get("attempts", 0)),
                    int(job.get("max_retries", 3)),
                    job.get("status", "scheduled"),
                    _to_iso(job.get("created_at", _utcnow())),
                    _to_iso(job.get("updated_at", _utcnow())),
                    job.get("last_error"),
                    json.dumps(job.get("payload", {}), default=str),
                ),
            )
            connection.commit()

    async def claim_due_jobs(self, limit: int = 10) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._claim_due_jobs_sync, limit)

    def _claim_due_jobs_sync(self, limit: int) -> List[Dict[str, Any]]:
        now_iso = _to_iso(_utcnow())
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE status IN ('scheduled', 'retrying') AND run_at <= ?
                ORDER BY priority DESC, run_at ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()

            job_ids = [row["job_id"] for row in rows]
            if job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                connection.execute(
                    f"UPDATE jobs SET status='queued', updated_at=? WHERE job_id IN ({placeholders})",
                    [_to_iso(_utcnow()), *job_ids],
                )
                connection.commit()

            return [self._row_to_job_dict(row) for row in rows]

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_job_sync, job_id)

    def _get_job_sync(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return self._row_to_job_dict(row) if row else None

    async def update_job_status(self, job_id: str, status: str, last_error: Optional[str] = None) -> None:
        await asyncio.to_thread(self._update_job_status_sync, job_id, status, last_error)

    def _update_job_status_sync(self, job_id: str, status: str, last_error: Optional[str]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status=?, updated_at=?, last_error=? WHERE job_id=?",
                (status, _to_iso(_utcnow()), last_error, job_id),
            )
            connection.commit()

    async def record_breaker_state(self, breaker_key: str, state: Dict[str, Any]) -> None:
        await asyncio.to_thread(self._record_breaker_state_sync, breaker_key, state)

    def _record_breaker_state_sync(self, breaker_key: str, state: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO breaker_states (
                    breaker_key, state, failure_count, success_count, opened_until,
                    last_failure_at, last_success_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(breaker_key) DO UPDATE SET
                    state=excluded.state,
                    failure_count=excluded.failure_count,
                    success_count=excluded.success_count,
                    opened_until=excluded.opened_until,
                    last_failure_at=excluded.last_failure_at,
                    last_success_at=excluded.last_success_at,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (
                    breaker_key,
                    state["state"],
                    int(state.get("failure_count", 0)),
                    int(state.get("success_count", 0)),
                    _to_iso(state.get("opened_until")),
                    _to_iso(state.get("last_failure_at")),
                    _to_iso(state.get("last_success_at")),
                    _to_iso(_utcnow()),
                    json.dumps(state.get("metadata", {}), default=str),
                ),
            )
            connection.commit()

    async def get_breaker_state(self, breaker_key: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_breaker_state_sync, breaker_key)

    def _get_breaker_state_sync(self, breaker_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM breaker_states WHERE breaker_key=?",
                (breaker_key,),
            ).fetchone()
            return self._row_to_breaker_dict(row) if row else None

    def _row_to_job_dict(self, row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        payload = json.loads(row["payload"] or "{}")
        return {
            "job_id": row["job_id"],
            "issue_id": row["issue_id"],
            "namespace": row["namespace"],
            "resource_name": row["resource_name"],
            "issue_type": row["issue_type"],
            "workflow_name": row["workflow_name"],
            "step_index": row["step_index"],
            "strategy": row["strategy"],
            "priority": row["priority"],
            "run_at": row["run_at"],
            "attempts": row["attempts"],
            "max_retries": row["max_retries"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_error": row["last_error"],
            "payload": payload,
        }

    def _row_to_breaker_dict(self, row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return {
            "breaker_key": row["breaker_key"],
            "state": row["state"],
            "failure_count": row["failure_count"],
            "success_count": row["success_count"],
            "opened_until": row["opened_until"],
            "last_failure_at": row["last_failure_at"],
            "last_success_at": row["last_success_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata"] or "{}"),
        }