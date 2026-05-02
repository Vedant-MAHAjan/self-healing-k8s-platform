"""Persistent asynchronous job scheduler for remediation workflows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from ..state_store import SQLiteStateStore
from ..utils.metrics import (
    job_queue_depth_gauge,
    remediation_attempts_counter,
    scheduled_jobs_counter,
    workflow_steps_counter,
)


logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return _utcnow()
    return datetime.fromisoformat(value)


@dataclass
class ScheduledJob:
    job_id: str
    issue_id: str
    namespace: str
    resource_name: str
    issue_type: str
    workflow_name: str
    step_index: int
    strategy: str
    priority: int
    run_at: datetime
    attempts: int = 0
    max_retries: int = 3
    status: str = "scheduled"
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "issue_id": self.issue_id,
            "namespace": self.namespace,
            "resource_name": self.resource_name,
            "issue_type": self.issue_type,
            "workflow_name": self.workflow_name,
            "step_index": self.step_index,
            "strategy": self.strategy,
            "priority": self.priority,
            "run_at": self.run_at.isoformat(),
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_error": self.last_error,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ScheduledJob":
        return cls(
            job_id=payload["job_id"],
            issue_id=payload["issue_id"],
            namespace=payload["namespace"],
            resource_name=payload["resource_name"],
            issue_type=payload["issue_type"],
            workflow_name=payload["workflow_name"],
            step_index=int(payload.get("step_index", 0)),
            strategy=payload["strategy"],
            priority=int(payload.get("priority", 50)),
            run_at=_parse_dt(payload.get("run_at")),
            attempts=int(payload.get("attempts", 0)),
            max_retries=int(payload.get("max_retries", 3)),
            status=payload.get("status", "scheduled"),
            payload=dict(payload.get("payload", {})),
            created_at=_parse_dt(payload.get("created_at")),
            updated_at=_parse_dt(payload.get("updated_at")),
            last_error=payload.get("last_error"),
        )


@dataclass
class JobExecutionResult:
    success: bool
    retryable: bool = False
    retry_delay_seconds: int = 0
    reason: str = ""
    follow_up_job: Optional[ScheduledJob] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


JobExecutor = Callable[[ScheduledJob], Awaitable[JobExecutionResult]]


class JobScheduler:
    """Queued and scheduled executor for remediation jobs."""

    def __init__(
        self,
        state_store: SQLiteStateStore,
        poll_interval: int = 5,
        worker_concurrency: int = 2,
    ):
        self.state_store = state_store
        self.poll_interval = poll_interval
        self.worker_concurrency = max(1, worker_concurrency)
        self._queue: asyncio.PriorityQueue[Tuple[float, float, str]] = asyncio.PriorityQueue()
        self._executor: Optional[JobExecutor] = None
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None
        self._worker_tasks: List[asyncio.Task] = []
        self._wake_event = asyncio.Event()

    def set_executor(self, executor: JobExecutor) -> None:
        self._executor = executor

    async def start(self) -> None:
        if self._running:
            return

        if self._executor is None:
            raise RuntimeError("Job executor must be configured before starting the scheduler")

        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop(), name="job-dispatch-loop")
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(index), name=f"job-worker-{index}")
            for index in range(self.worker_concurrency)
        ]
        logger.info(
            "job_scheduler_started",
            poll_interval=self.poll_interval,
            worker_concurrency=self.worker_concurrency,
        )

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._wake_event.set()

        tasks = [task for task in [self._dispatch_task, *self._worker_tasks] if task]
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._dispatch_task = None
        self._worker_tasks = []
        logger.info("job_scheduler_stopped")

    async def schedule(self, job: ScheduledJob) -> None:
        job.status = "scheduled"
        job.updated_at = _utcnow()
        await self.state_store.upsert_job(job.to_dict())
        self._wake_event.set()
        job_queue_depth_gauge.set(self._queue.qsize())
        scheduled_jobs_counter.labels(workflow=job.workflow_name, status=job.status).inc()

        logger.info(
            "job_scheduled",
            job_id=job.job_id,
            issue_id=job.issue_id,
            strategy=job.strategy,
            workflow=job.workflow_name,
            run_at=job.run_at.isoformat(),
            priority=job.priority,
        )

    async def _dispatch_loop(self) -> None:
        try:
            while self._running:
                due_jobs = await self.state_store.claim_due_jobs(limit=self.worker_concurrency * 10)
                for job_data in due_jobs:
                    job = ScheduledJob.from_dict(job_data)
                    await self._queue.put((-job.priority, job.run_at.timestamp(), job.job_id))
                    job_queue_depth_gauge.set(self._queue.qsize())

                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=self.poll_interval)
                except asyncio.TimeoutError:
                    pass
                finally:
                    self._wake_event.clear()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("job_dispatch_loop_failed", error=str(exc), exc_info=True)

    async def _worker_loop(self, worker_index: int) -> None:
        try:
            while self._running:
                priority, run_at_ts, job_id = await self._queue.get()

                try:
                    if self._executor is None:
                        raise RuntimeError("job executor not configured")

                    job_data = await self.state_store.get_job(job_id)
                    if not job_data:
                        continue

                    job = ScheduledJob.from_dict(job_data)
                    job.status = "running"
                    job.updated_at = _utcnow()
                    await self.state_store.upsert_job(job.to_dict())
                    remediation_attempts_counter.labels(strategy=job.strategy, status="started").inc()
                    workflow_steps_counter.labels(
                        workflow=job.workflow_name,
                        step=job.strategy,
                        status="running",
                    ).inc()

                    logger.info(
                        "job_execution_started",
                        worker_index=worker_index,
                        job_id=job.job_id,
                        issue_id=job.issue_id,
                        strategy=job.strategy,
                        workflow=job.workflow_name,
                        step_index=job.step_index,
                    )

                    try:
                        result = await self._executor(job)
                    except Exception as exc:
                        logger.error(
                            "job_executor_raised",
                            job_id=job.job_id,
                            error=str(exc),
                            exc_info=True,
                        )
                        result = JobExecutionResult(success=False, retryable=False, reason=str(exc))

                    await self._apply_result(job, result)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("job_worker_loop_failed", worker_index=worker_index, error=str(exc), exc_info=True)

    async def _apply_result(self, job: ScheduledJob, result: JobExecutionResult) -> None:
        now = _utcnow()

        if result.success:
            job.status = "completed"
            job.last_error = None
            job.updated_at = now
            await self.state_store.upsert_job(job.to_dict())
            remediation_attempts_counter.labels(strategy=job.strategy, status="success").inc()
            workflow_steps_counter.labels(
                workflow=job.workflow_name,
                step=job.strategy,
                status="completed",
            ).inc()
            logger.info("job_completed", job_id=job.job_id, issue_id=job.issue_id)

            if result.follow_up_job:
                await self.schedule(result.follow_up_job)
            return

        if result.retryable:
            job.attempts += 1
            job.status = "retrying"
            job.run_at = now + timedelta(seconds=max(0, result.retry_delay_seconds))
            job.last_error = result.reason
            job.updated_at = now
            await self.state_store.upsert_job(job.to_dict())
            self._wake_event.set()
            job_queue_depth_gauge.set(self._queue.qsize())
            scheduled_jobs_counter.labels(workflow=job.workflow_name, status="retrying").inc()
            remediation_attempts_counter.labels(strategy=job.strategy, status="retrying").inc()
            workflow_steps_counter.labels(
                workflow=job.workflow_name,
                step=job.strategy,
                status="retrying",
            ).inc()
            logger.info(
                "job_retried",
                job_id=job.job_id,
                issue_id=job.issue_id,
                attempts=job.attempts,
                next_run_at=job.run_at.isoformat(),
                reason=result.reason,
            )
            return

        job.status = "failed"
        job.last_error = result.reason
        job.updated_at = now
        await self.state_store.upsert_job(job.to_dict())
        remediation_attempts_counter.labels(strategy=job.strategy, status="failed").inc()
        workflow_steps_counter.labels(
            workflow=job.workflow_name,
            step=job.strategy,
            status="failed",
        ).inc()

        logger.warning(
            "job_failed",
            job_id=job.job_id,
            issue_id=job.issue_id,
            reason=result.reason,
        )

        if result.follow_up_job:
            await self.schedule(result.follow_up_job)