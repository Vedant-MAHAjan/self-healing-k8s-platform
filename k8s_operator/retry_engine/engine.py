"""Retry and backoff engine for remediation jobs."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

from ..config_manager import ConfigManager, ResolvedPolicy
from ..models import Diagnosis, Issue, RemediationStrategy


logger = structlog.get_logger()


class FailureClassification(Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass
class RetryDecision:
    should_retry: bool
    retry_count: int
    delay_seconds: int
    classification: FailureClassification
    reason: str


class RetryEngine:
    """Compute exponential backoff with jitter and failure classification."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def classify_failure(
        self,
        issue: Issue,
        diagnosis: Diagnosis,
        error_message: Optional[str] = None,
    ) -> FailureClassification:
        if diagnosis.requires_manual_intervention:
            return FailureClassification.PERMANENT

        if diagnosis.recommended_strategy in (
            RemediationStrategy.NO_ACTION,
            RemediationStrategy.MANUAL_INTERVENTION,
        ):
            return FailureClassification.PERMANENT

        if issue.issue_type.value == "PodPending":
            return FailureClassification.PERMANENT

        if error_message:
            lower_error = error_message.lower()
            permanent_markers = (
                "forbidden",
                "unauthorized",
                "not found",
                "cannot find",
                "invalid",
                "permission denied",
            )
            if any(marker in lower_error for marker in permanent_markers):
                return FailureClassification.PERMANENT

        return FailureClassification.TRANSIENT

    def compute_delay(self, retry_count: int, policy: ResolvedPolicy) -> int:
        backoff = policy.retry.backoff
        delay = backoff.base_seconds * (2 ** retry_count)
        delay = min(delay, backoff.max_seconds)
        jitter = random.uniform(0, backoff.jitter_seconds) if backoff.jitter_seconds > 0 else 0
        computed_delay = int(delay + jitter)
        logger.info(
            "retry_delay_computed",
            retry_count=retry_count,
            delay_seconds=computed_delay,
            base_seconds=backoff.base_seconds,
            max_seconds=backoff.max_seconds,
        )
        return max(0, computed_delay)

    def build_retry_decision(
        self,
        retry_count: int,
        policy: ResolvedPolicy,
        issue: Issue,
        diagnosis: Diagnosis,
        error_message: Optional[str] = None,
    ) -> RetryDecision:
        classification = self.classify_failure(issue, diagnosis, error_message)
        effective_max_retries = min(policy.max_retries, policy.retry.max_retries)

        if retry_count >= effective_max_retries:
            return RetryDecision(
                should_retry=False,
                retry_count=retry_count,
                delay_seconds=0,
                classification=classification,
                reason="retry_limit_reached",
            )

        if classification == FailureClassification.PERMANENT:
            return RetryDecision(
                should_retry=False,
                retry_count=retry_count,
                delay_seconds=0,
                classification=classification,
                reason="permanent_failure_classified",
            )

        delay_seconds = self.compute_delay(retry_count, policy)
        return RetryDecision(
            should_retry=True,
            retry_count=retry_count,
            delay_seconds=delay_seconds,
            classification=classification,
            reason="transient_failure_backoff",
        )