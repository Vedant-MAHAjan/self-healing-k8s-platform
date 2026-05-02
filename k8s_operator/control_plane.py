"""Autonomous control system that coordinates policy, scheduling, and remediation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import structlog

from .circuit_breaker import CircuitBreaker, CircuitBreakerState
from .config import Settings
from .config_manager import ConfigManager
from .decision_engine import ControlDecision, DecisionAction, DecisionEngine
from .diagnosis.ai_engine import AIEngine
from .metrics import MetricsAggregator
from .models import (
    Diagnosis,
    DeploymentInfo,
    Issue,
    IssueType,
    PodInfo,
    RemediationStrategy,
)
from .remediation.strategy_manager import StrategyManager
from .retry_engine import FailureClassification, RetryDecision, RetryEngine
from .scheduler import JobExecutionResult, JobScheduler, ScheduledJob
from .state_store import SQLiteStateStore
from .workflows import WorkflowEngine, WorkflowPlan, WorkflowStep
from .utils.metrics import control_decisions_counter, fixes_applied_counter, fixes_failed_counter


logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value) if value is not None else ""
    if not text:
        return _utcnow()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class AutonomousControlSystem:
    """Policy-driven, stateful autonomous control layer."""

    def __init__(self, settings: Settings, ai_engine: AIEngine, strategy_manager: StrategyManager):
        self.settings = settings
        self.ai_engine = ai_engine
        self.strategy_manager = strategy_manager

        self.config_manager = ConfigManager(settings)
        self.state_store = SQLiteStateStore(settings.state_store_path)
        self.metrics_aggregator = MetricsAggregator(self.state_store)
        self.decision_engine = DecisionEngine(self.config_manager)
        self.retry_engine = RetryEngine(self.config_manager)
        self.circuit_breaker = CircuitBreaker(self.state_store)
        self.workflow_engine = WorkflowEngine(self.config_manager)
        self.scheduler = JobScheduler(
            self.state_store,
            poll_interval=settings.scheduler_poll_interval,
            worker_concurrency=settings.scheduler_worker_concurrency,
        )
        self.scheduler.set_executor(self.execute_job)
        self._started = False

        logger.info(
            "autonomous_control_system_initialized",
            policy_path=str(self.config_manager.policy_path),
            state_store_path=str(self.state_store.db_path),
        )

    async def start(self) -> None:
        if self._started:
            return

        await self.scheduler.start()
        self._started = True
        logger.info("autonomous_control_system_started")

    async def stop(self) -> None:
        if not self._started:
            return

        await self.scheduler.stop()
        self._started = False
        logger.info("autonomous_control_system_stopped")

    async def process_issue(self, issue: Issue) -> Optional[ControlDecision]:
        """Record, diagnose, decide, and queue remediation for a detected issue."""
        await self.state_store.record_incident(
            issue,
            status="open",
            metadata={"source": "detector", "severity": issue.severity},
        )

        metrics = await self.metrics_aggregator.collect(issue)
        history = await self._build_history(issue)

        logger.info(
            "autonomous_issue_processing_started",
            issue_id=issue.issue_id,
            issue_type=issue.issue_type.value,
            namespace=issue.resource_namespace,
            resource_name=issue.resource_name,
        )

        diagnosis = await self.ai_engine.diagnose(issue)
        await self.state_store.record_diagnosis(issue.issue_id, diagnosis)

        decision = self.decision_engine.evaluate(issue, diagnosis, metrics, history)
        await self.state_store.record_decision(issue.issue_id, decision.to_dict())
        control_decisions_counter.labels(
            action=decision.action.value,
            strategy=decision.strategy.value,
            namespace=issue.resource_namespace,
        ).inc()

        if decision.action in {DecisionAction.IGNORE, DecisionAction.MANUAL_REVIEW, DecisionAction.ESCALATE}:
            status = {
                DecisionAction.IGNORE: "ignored",
                DecisionAction.MANUAL_REVIEW: "manual_review",
                DecisionAction.ESCALATE: "escalated",
            }[decision.action]
            await self.state_store.record_incident(
                issue,
                status=status,
                metadata={"decision": decision.to_dict(), "diagnosis": diagnosis.reasoning},
            )
            logger.info(
                "autonomous_decision_terminal",
                issue_id=issue.issue_id,
                action=decision.action.value,
                reason=decision.reason,
            )
            return decision

        workflow = self.workflow_engine.build_plan(issue, diagnosis, decision)
        first_step = workflow.steps[0]
        job = self._build_job(issue, diagnosis, decision, workflow, 0, first_step)

        await self.scheduler.schedule(job)

        logger.info(
            "autonomous_job_enqueued",
            issue_id=issue.issue_id,
            decision=decision.action.value,
            strategy=first_step.strategy,
            workflow=workflow.workflow_name,
            job_id=job.job_id,
        )
        return decision

    async def execute_job(self, job: ScheduledJob) -> JobExecutionResult:
        issue = self._issue_from_payload(job.payload.get("issue", {}))
        diagnosis = self._diagnosis_from_payload(job.payload.get("diagnosis", {}), issue)
        decision = ControlDecision.from_dict(job.payload.get("decision", {}))
        workflow = WorkflowPlan.from_dict(job.payload.get("workflow", {}))

        policy = self.config_manager.resolve_policy(issue)
        breaker_key = self._breaker_key(issue)

        if not await self.circuit_breaker.allow(breaker_key, policy.circuit_breaker):
            return JobExecutionResult(
                success=False,
                retryable=True,
                retry_delay_seconds=policy.circuit_breaker.recovery_timeout_seconds,
                reason="circuit_breaker_open",
            )

        current_step = workflow.steps[job.step_index]
        step_strategy = self._strategy_from_name(current_step.strategy)
        step_diagnosis = replace(diagnosis, recommended_strategy=step_strategy)

        execution_error: Optional[str] = None
        try:
            success = await self.strategy_manager.execute(step_diagnosis, dry_run=self.settings.dry_run)
        except Exception as exc:
            success = False
            execution_error = str(exc)

        if success:
            await self.circuit_breaker.record_success(breaker_key)
            await self.state_store.mark_incident_resolved(issue.issue_id)
            await self.metrics_aggregator.collect(issue)
            fixes_applied_counter.labels(
                strategy=current_step.strategy,
                namespace=issue.resource_namespace,
            ).inc()
            return JobExecutionResult(success=True, reason="remediation_successful")

        await self.circuit_breaker.record_failure(
            breaker_key,
            policy.circuit_breaker,
            reason=execution_error or "strategy_execution_failed",
        )

        retry_decision = self.retry_engine.build_retry_decision(
            retry_count=job.attempts,
            policy=policy,
            issue=issue,
            diagnosis=diagnosis,
            error_message=execution_error,
        )

        if retry_decision.should_retry:
            return JobExecutionResult(
                success=False,
                retryable=True,
                retry_delay_seconds=retry_decision.delay_seconds,
                reason=retry_decision.reason,
            )

        if retry_decision.classification != FailureClassification.PERMANENT:
            next_step = self.workflow_engine.next_step(workflow, job.step_index)
            if next_step:
                follow_up_job = self._build_job(
                    issue=issue,
                    diagnosis=diagnosis,
                    decision=decision,
                    workflow=workflow,
                    step_index=job.step_index + 1,
                    step=next_step,
                )
                return JobExecutionResult(
                    success=False,
                    retryable=False,
                    reason=f"advancing_to_{next_step.name}",
                    follow_up_job=follow_up_job,
                )

        await self.state_store.record_incident(
            issue,
            status="escalated",
            metadata={
                "workflow": workflow.workflow_name,
                "last_step": current_step.name,
                "error": execution_error or retry_decision.reason,
            },
        )
        await self.metrics_aggregator.collect(issue)
        fixes_failed_counter.labels(
            strategy=current_step.strategy,
            namespace=issue.resource_namespace,
        ).inc()
        return JobExecutionResult(
            success=False,
            retryable=False,
            reason=execution_error or retry_decision.reason,
        )

    async def _build_history(self, issue: Issue) -> Dict[str, Any]:
        breaker_snapshot = await self.circuit_breaker.get_snapshot(self._breaker_key(issue))
        recent_failures = await self.state_store.count_recent_job_failures(
            issue.resource_namespace,
            issue.resource_name,
            window_minutes=15,
        )
        return {
            "recent_failures": recent_failures,
            "breaker_open": breaker_snapshot.state == CircuitBreakerState.OPEN,
            "breaker_state": breaker_snapshot.state.value,
        }

    def _build_job(
        self,
        issue: Issue,
        diagnosis: Diagnosis,
        decision: ControlDecision,
        workflow: WorkflowPlan,
        step_index: int,
        step: WorkflowStep,
    ) -> ScheduledJob:
        job_workflow = WorkflowPlan(
            workflow_name=workflow.workflow_name,
            steps=workflow.steps,
            current_step_index=step_index,
            metadata=dict(workflow.metadata),
        )
        payload = self.workflow_engine.build_job_payload(
            issue=issue,
            diagnosis=diagnosis,
            decision=decision,
            workflow=job_workflow,
            step_index=step_index,
        )

        return ScheduledJob(
            job_id=f"{decision.decision_id}-step-{step_index}",
            issue_id=issue.issue_id,
            namespace=issue.resource_namespace,
            resource_name=issue.resource_name,
            issue_type=issue.issue_type.value,
            workflow_name=workflow.workflow_name,
            step_index=step_index,
            strategy=step.strategy,
            priority=decision.priority,
            run_at=_utcnow() + timedelta(seconds=max(0, decision.delay_seconds + step.delay_seconds)),
            attempts=0,
            max_retries=min(decision.max_retries, step.max_retries),
            status="scheduled",
            payload=payload,
        )

    def _strategy_from_name(self, strategy_name: str) -> RemediationStrategy:
        try:
            return RemediationStrategy(strategy_name)
        except ValueError:
            logger.warning("unknown_remediation_strategy", strategy=strategy_name)
            return RemediationStrategy.NO_ACTION

    def _breaker_key(self, issue: Issue) -> str:
        return f"{issue.resource_namespace}/{issue.resource_name}"

    def _issue_from_payload(self, payload: Dict[str, Any]) -> Issue:
        pod_info = self._pod_info_from_payload(payload.get("pod_info"))
        deployment_info = self._deployment_info_from_payload(payload.get("deployment_info"))
        return Issue(
            issue_id=payload["issue_id"],
            issue_type=IssueType(payload["issue_type"]),
            resource_kind=payload["resource_kind"],
            resource_name=payload["resource_name"],
            resource_namespace=payload["resource_namespace"],
            description=payload.get("description", ""),
            severity=payload.get("severity", "medium"),
            detected_at=_parse_datetime(payload["detected_at"]),
            pod_info=pod_info,
            deployment_info=deployment_info,
            logs=list(payload.get("logs", [])),
            events=list(payload.get("events", [])),
            metrics=dict(payload.get("metrics", {})),
            alert_labels=dict(payload.get("alert_labels", {})),
        )

    def _diagnosis_from_payload(self, payload: Dict[str, Any], issue: Issue) -> Diagnosis:
        return Diagnosis(
            issue=issue,
            root_cause=payload.get("root_cause", "Unknown"),
            analysis=payload.get("analysis", ""),
            recommended_strategy=self._strategy_from_name(payload.get("recommended_strategy", "no_action")),
            confidence=float(payload.get("confidence", 0.0)),
            reasoning=payload.get("reasoning", ""),
            alternative_strategies=[
                self._strategy_from_name(strategy_name)
                for strategy_name in payload.get("alternative_strategies", [])
            ],
            requires_manual_intervention=bool(payload.get("requires_manual_intervention", False)),
            suggested_actions=list(payload.get("suggested_actions", [])),
        )

    def _pod_info_from_payload(self, payload: Optional[Dict[str, Any]]) -> Optional[PodInfo]:
        if not payload:
            return None
        creation_timestamp = payload.get("creation_timestamp")
        return PodInfo(
            name=payload["name"],
            namespace=payload["namespace"],
            uid=payload["uid"],
            status=payload.get("status", "Unknown"),
            restart_count=int(payload.get("restart_count", 0)),
            container_statuses=list(payload.get("container_statuses", [])),
            node_name=payload.get("node_name"),
            labels=dict(payload.get("labels", {})),
            annotations=dict(payload.get("annotations", {})),
            creation_timestamp=_parse_datetime(creation_timestamp) if creation_timestamp else None,
        )

    def _deployment_info_from_payload(self, payload: Optional[Dict[str, Any]]) -> Optional[DeploymentInfo]:
        if not payload:
            return None
        return DeploymentInfo(
            name=payload["name"],
            namespace=payload["namespace"],
            uid=payload["uid"],
            replicas=int(payload.get("replicas", 0)),
            ready_replicas=int(payload.get("ready_replicas", 0)),
            available_replicas=int(payload.get("available_replicas", 0)),
            labels=dict(payload.get("labels", {})),
            selector=dict(payload.get("selector", {})),
            revision=payload.get("revision"),
        )