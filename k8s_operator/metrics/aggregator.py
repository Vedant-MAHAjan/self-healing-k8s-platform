"""Metrics aggregation layer for trend-based control decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import structlog

from ..models import Issue
from ..state_store import SQLiteStateStore
from ..utils.metrics import active_issues_gauge, service_issue_frequency_gauge


logger = structlog.get_logger()


@dataclass
class MetricsSnapshot:
    namespace: str
    resource_name: str
    issue_type: str
    issue_frequency_5m: int
    issue_frequency_15m: int
    failure_count_15m: int
    open_issues: int
    error_log_count: int
    event_count: int
    trend: str
    unstable: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


class MetricsAggregator:
    """Aggregate time-window signals for policy-driven decisions."""

    def __init__(self, state_store: SQLiteStateStore):
        self.state_store = state_store

    async def collect(self, issue: Issue) -> MetricsSnapshot:
        frequency_5m = await self.state_store.count_recent_incidents(
            issue.resource_namespace,
            issue.resource_name,
            issue.issue_type.value,
            window_minutes=5,
        )
        frequency_15m = await self.state_store.count_recent_incidents(
            issue.resource_namespace,
            issue.resource_name,
            issue.issue_type.value,
            window_minutes=15,
        )
        failure_count_15m = await self.state_store.count_recent_job_failures(
            issue.resource_namespace,
            issue.resource_name,
            window_minutes=15,
        )
        open_issues = await self.state_store.count_open_issues(issue.resource_namespace)

        error_log_count = sum(
            1
            for line in issue.logs
            if any(keyword in line.lower() for keyword in ("error", "exception", "traceback", "failed"))
        )
        event_count = len(issue.events)

        trend = self._classify_trend(frequency_5m, frequency_15m)
        unstable = frequency_5m >= 3 or failure_count_15m >= 2 or error_log_count >= 5

        active_issues_gauge.labels(namespace=issue.resource_namespace).set(open_issues)
        service_issue_frequency_gauge.labels(
            namespace=issue.resource_namespace,
            resource_name=issue.resource_name,
            issue_type=issue.issue_type.value,
        ).set(frequency_5m)

        snapshot = MetricsSnapshot(
            namespace=issue.resource_namespace,
            resource_name=issue.resource_name,
            issue_type=issue.issue_type.value,
            issue_frequency_5m=frequency_5m,
            issue_frequency_15m=frequency_15m,
            failure_count_15m=failure_count_15m,
            open_issues=open_issues,
            error_log_count=error_log_count,
            event_count=event_count,
            trend=trend,
            unstable=unstable,
            metadata={
                "restart_count": issue.pod_info.restart_count if issue.pod_info else 0,
                "node_name": issue.pod_info.node_name if issue.pod_info else None,
            },
        )

        logger.info(
            "metrics_snapshot_built",
            namespace=issue.resource_namespace,
            resource_name=issue.resource_name,
            issue_type=issue.issue_type.value,
            issue_frequency_5m=frequency_5m,
            issue_frequency_15m=frequency_15m,
            failure_count_15m=failure_count_15m,
            trend=trend,
            unstable=unstable,
        )
        return snapshot

    def _classify_trend(self, frequency_5m: int, frequency_15m: int) -> str:
        if frequency_5m == 0 and frequency_15m == 0:
            return "stable"
        if frequency_5m >= max(2, frequency_15m + 1):
            return "rising"
        if frequency_15m > frequency_5m:
            return "cooling"
        return "stable"