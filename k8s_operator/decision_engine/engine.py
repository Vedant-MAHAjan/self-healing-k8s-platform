"""Policy-driven decision engine that separates diagnosis from action."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

import structlog

from ..config_manager import ConfigManager, ResolvedPolicy
from ..metrics.aggregator import MetricsSnapshot
from ..models import Diagnosis, Issue, RemediationStrategy


logger = structlog.get_logger()


class DecisionAction(Enum):
    IMMEDIATE_REMEDIATION = "immediate_remediation"
    DELAY_AND_RETRY = "delay_and_retry"
    ESCALATE = "escalate"
    IGNORE = "ignore"
    MANUAL_REVIEW = "manual_review"


@dataclass
class ControlDecision:
    decision_id: str
    issue_id: str
    action: DecisionAction
    strategy: RemediationStrategy
    confidence: float
    priority: int
    max_retries: int
    delay_seconds: int
    workflow_name: str
    reason: str
    retryable: bool = True
    policy_source: str = "defaults"
    service_key: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "issue_id": self.issue_id,
            "action": self.action.value,
            "strategy": self.strategy.value,
            "confidence": self.confidence,
            "priority": self.priority,
            "max_retries": self.max_retries,
            "delay_seconds": self.delay_seconds,
            "workflow_name": self.workflow_name,
            "reason": self.reason,
            "retryable": self.retryable,
            "policy_source": self.policy_source,
            "service_key": self.service_key,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ControlDecision":
        return cls(
            decision_id=payload["decision_id"],
            issue_id=payload["issue_id"],
            action=DecisionAction(payload["action"]),
            strategy=RemediationStrategy(payload["strategy"]),
            confidence=float(payload.get("confidence", 0.0)),
            priority=int(payload.get("priority", 50)),
            max_retries=int(payload.get("max_retries", 3)),
            delay_seconds=int(payload.get("delay_seconds", 0)),
            workflow_name=payload.get("workflow_name", "default"),
            reason=payload.get("reason", ""),
            retryable=bool(payload.get("retryable", True)),
            policy_source=payload.get("policy_source", "defaults"),
            service_key=payload.get("service_key", "default"),
            metadata=dict(payload.get("metadata", {})),
            created_at=datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.utcnow(),
        )


class DecisionEngine:
    """Deterministic policy layer between diagnosis and remediation."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def evaluate(
        self,
        issue: Issue,
        diagnosis: Diagnosis,
        metrics: MetricsSnapshot,
        history: Optional[Dict[str, Any]] = None,
    ) -> ControlDecision:
        policy = self.config_manager.resolve_policy(issue)
        history = history or {}

        action = DecisionAction.IMMEDIATE_REMEDIATION
        reason = "policy_default"
        delay_seconds = policy.delay_seconds
        strategy = policy.strategy
        retryable = True

        recent_failures = int(history.get("recent_failures", 0))
        breaker_open = bool(history.get("breaker_open", False))
        confidence = float(diagnosis.confidence)

        if diagnosis.requires_manual_intervention or diagnosis.recommended_strategy in (
            RemediationStrategy.NO_ACTION,
            RemediationStrategy.MANUAL_INTERVENTION,
        ):
            action = DecisionAction.MANUAL_REVIEW
            strategy = RemediationStrategy.MANUAL_INTERVENTION
            retryable = False
            reason = "diagnosis_requires_manual_intervention"
        elif breaker_open:
            action = DecisionAction.ESCALATE
            retryable = False
            reason = "circuit_breaker_open"
        elif recent_failures >= policy.max_retries:
            action = DecisionAction.ESCALATE
            retryable = False
            reason = "historical_failures_exceeded"
        elif metrics.unstable and confidence < policy.confidence_threshold:
            action = DecisionAction.DELAY_AND_RETRY
            delay_seconds = max(delay_seconds, 2 * int(policy.retry.backoff.base_seconds))
            reason = "unstable_service_low_confidence"
        elif metrics.issue_frequency_5m >= policy.issue_frequency_threshold and confidence < 0.7:
            action = DecisionAction.DELAY_AND_RETRY
            delay_seconds = max(delay_seconds, int(policy.retry.backoff.base_seconds))
            reason = "high_frequency_low_confidence"
        elif issue.severity.lower() == "critical" or confidence >= policy.confidence_threshold:
            action = DecisionAction.IMMEDIATE_REMEDIATION
            reason = "high_confidence_or_critical"
        else:
            action = DecisionAction.DELAY_AND_RETRY
            delay_seconds = max(delay_seconds, int(policy.retry.backoff.base_seconds))
            reason = "conservative_retry"

        if action == DecisionAction.IGNORE:
            retryable = False
        elif action == DecisionAction.MANUAL_REVIEW:
            retryable = False

        if action == DecisionAction.ESCALATE:
            delay_seconds = 0

        if action == DecisionAction.DELAY_AND_RETRY and delay_seconds <= 0:
            delay_seconds = int(policy.retry.backoff.base_seconds)

        if action.value not in policy.allowed_actions and action != DecisionAction.MANUAL_REVIEW:
            logger.warning(
                "strategy_not_allowed_by_policy",
                issue_id=issue.issue_id,
                action=action.value,
                allowed_actions=policy.allowed_actions,
            )
            action = DecisionAction.ESCALATE
            retryable = False
            reason = "strategy_blocked_by_policy"

        decision = ControlDecision(
            decision_id=f"{issue.issue_id}-{action.value}-{strategy.value}",
            issue_id=issue.issue_id,
            action=action,
            strategy=strategy,
            confidence=confidence,
            priority=policy.priority,
            max_retries=policy.max_retries,
            delay_seconds=delay_seconds,
            workflow_name=policy.workflow_name,
            reason=reason,
            retryable=retryable,
            policy_source=policy.policy_source,
            service_key=policy.service_key,
            metadata={
                "issue_frequency_5m": metrics.issue_frequency_5m,
                "issue_frequency_15m": metrics.issue_frequency_15m,
                "failure_count_15m": metrics.failure_count_15m,
                "trend": metrics.trend,
                "unstable": metrics.unstable,
                "confidence_threshold": policy.confidence_threshold,
            },
        )

        logger.info(
            "control_decision_made",
            issue_id=issue.issue_id,
            action=decision.action.value,
            strategy=decision.strategy.value,
            confidence=decision.confidence,
            priority=decision.priority,
            delay_seconds=decision.delay_seconds,
            workflow=decision.workflow_name,
            reason=decision.reason,
        )
        return decision