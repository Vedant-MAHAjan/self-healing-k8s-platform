"""Policy configuration manager for the autonomous control plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import structlog
import yaml
from pydantic import BaseModel, Field, ValidationError

from ..config import Settings
from ..models import Issue, RemediationStrategy


logger = structlog.get_logger()


class BackoffPolicy(BaseModel):
    base_seconds: float = 5.0
    max_seconds: float = 300.0
    jitter_seconds: float = 2.0


class CircuitBreakerPolicy(BaseModel):
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60
    half_open_probes: int = 1
    rolling_window_minutes: int = 5


class RetryPolicy(BaseModel):
    max_retries: int = 3
    backoff: BackoffPolicy = Field(default_factory=BackoffPolicy)


class PolicyDefaults(BaseModel):
    action: str = "immediate_remediation"
    strategy: str = "restart_pod"
    confidence_threshold: float = 0.75
    issue_frequency_threshold: int = 5
    max_retries: int = 3
    priority: int = 50
    workflow: str = "default"
    delay_seconds: int = 0
    allowed_actions: List[str] = Field(
        default_factory=lambda: [
            "immediate_remediation",
            "delay_and_retry",
            "escalate",
            "ignore",
            "manual_review",
        ]
    )
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    circuit_breaker: CircuitBreakerPolicy = Field(default_factory=CircuitBreakerPolicy)


class IssuePolicy(BaseModel):
    action: Optional[str] = None
    strategy: Optional[str] = None
    confidence_threshold: Optional[float] = None
    issue_frequency_threshold: Optional[int] = None
    max_retries: Optional[int] = None
    priority: Optional[int] = None
    workflow: Optional[str] = None
    delay_seconds: Optional[int] = None
    allowed_actions: Optional[List[str]] = None


class WorkflowStepConfig(BaseModel):
    name: str
    strategy: str
    delay_seconds: int = 0
    max_retries: int = 1
    stop_on_success: bool = True


class WorkflowConfig(BaseModel):
    name: str
    steps: List[WorkflowStepConfig] = Field(default_factory=list)


class ControlPolicy(BaseModel):
    version: int = 1
    defaults: PolicyDefaults = Field(default_factory=PolicyDefaults)
    issue_policies: Dict[str, IssuePolicy] = Field(default_factory=dict)
    service_overrides: Dict[str, IssuePolicy] = Field(default_factory=dict)
    workflows: Dict[str, WorkflowConfig] = Field(default_factory=dict)


@dataclass
class ResolvedPolicy:
    action: str
    strategy: RemediationStrategy
    confidence_threshold: float
    issue_frequency_threshold: int
    max_retries: int
    priority: int
    workflow_name: str
    delay_seconds: int
    allowed_actions: List[str] = field(default_factory=list)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    circuit_breaker: CircuitBreakerPolicy = field(default_factory=CircuitBreakerPolicy)
    policy_source: str = "defaults"
    service_key: str = "default"


class ConfigManager:
    """Loads and resolves policy decisions from YAML configuration."""

    def __init__(self, settings: Settings, policy_path: Optional[str] = None):
        self.settings = settings
        default_path = Path(__file__).with_name("default_policy.yaml")
        self.policy_path = Path(
            policy_path or settings.control_policy_path or default_path
        )
        self._policy: Optional[ControlPolicy] = None
        self._mtime: Optional[float] = None
        self.reload(force=True)

    def reload(self, force: bool = False) -> ControlPolicy:
        """Load policy from disk and validate it."""
        if not force and self._policy is not None and self.policy_path.exists():
            current_mtime = self.policy_path.stat().st_mtime
            if self._mtime == current_mtime:
                return self._policy

        if self.policy_path.exists():
            raw_data = yaml.safe_load(self.policy_path.read_text()) or {}
            self._mtime = self.policy_path.stat().st_mtime
        else:
            logger.warning(
                "policy_file_missing",
                path=str(self.policy_path),
                message="Using embedded default control policy",
            )
            raw_data = self._fallback_policy_data()
            self._mtime = None

        try:
            self._policy = ControlPolicy.model_validate(raw_data)
        except ValidationError as exc:
            logger.error(
                "policy_validation_failed",
                path=str(self.policy_path),
                error=str(exc),
            )
            raise

        logger.info("policy_loaded", path=str(self.policy_path), version=self._policy.version)
        return self._policy

    def reload_if_needed(self) -> ControlPolicy:
        return self.reload(force=False)

    def get_policy(self) -> ControlPolicy:
        return self.reload_if_needed()

    def get_workflow(self, workflow_name: Optional[str]) -> Optional[WorkflowConfig]:
        if not workflow_name:
            return None
        policy = self.get_policy()
        return policy.workflows.get(workflow_name)

    def resolve_policy(self, issue: Issue) -> ResolvedPolicy:
        policy = self.get_policy()
        issue_key = issue.issue_type.value
        issue_policy = policy.issue_policies.get(issue_key) or policy.issue_policies.get(
            issue.issue_type.name
        )

        service_key = f"{issue.resource_namespace}/{issue.resource_name}"
        service_policy = policy.service_overrides.get(service_key) or policy.service_overrides.get(
            f"{issue.resource_namespace}/default"
        )

        merged = self._merge_policy(policy.defaults, issue_policy, service_policy)

        strategy_value = merged.get("strategy", policy.defaults.strategy)
        try:
            strategy = RemediationStrategy(strategy_value)
        except ValueError:
            logger.warning("invalid_strategy_in_policy", strategy=strategy_value)
            strategy = RemediationStrategy.RESTART_POD

        return ResolvedPolicy(
            action=merged.get("action", policy.defaults.action),
            strategy=strategy,
            confidence_threshold=float(
                merged.get("confidence_threshold", policy.defaults.confidence_threshold)
            ),
            issue_frequency_threshold=int(
                merged.get("issue_frequency_threshold", policy.defaults.issue_frequency_threshold)
            ),
            max_retries=int(merged.get("max_retries", policy.defaults.max_retries)),
            priority=int(merged.get("priority", policy.defaults.priority)),
            workflow_name=str(merged.get("workflow", policy.defaults.workflow)),
            delay_seconds=int(merged.get("delay_seconds", policy.defaults.delay_seconds)),
            allowed_actions=list(
                merged.get("allowed_actions", policy.defaults.allowed_actions)
            ),
            retry=policy.defaults.retry,
            circuit_breaker=policy.defaults.circuit_breaker,
            policy_source="service_override" if service_policy else ("issue_policy" if issue_policy else "defaults"),
            service_key=service_key,
        )

    def _merge_policy(
        self,
        defaults: PolicyDefaults,
        issue_policy: Optional[IssuePolicy],
        service_policy: Optional[IssuePolicy],
    ) -> Dict[str, object]:
        merged = defaults.model_dump(exclude_none=True)
        if issue_policy:
            merged.update(issue_policy.model_dump(exclude_none=True))
        if service_policy:
            merged.update(service_policy.model_dump(exclude_none=True))
        return merged

    def _fallback_policy_data(self) -> Dict[str, object]:
        return {
            "version": 1,
            "defaults": {
                "action": "immediate_remediation",
                "strategy": "restart_pod",
                "confidence_threshold": 0.75,
                "issue_frequency_threshold": 5,
                "max_retries": 3,
                "priority": 50,
                "workflow": "default",
                "delay_seconds": 0,
                "retry": {
                    "max_retries": 3,
                    "backoff": {
                        "base_seconds": 5,
                        "max_seconds": 120,
                        "jitter_seconds": 2,
                    },
                },
                "circuit_breaker": {
                    "failure_threshold": 5,
                    "recovery_timeout_seconds": 60,
                    "half_open_probes": 1,
                    "rolling_window_minutes": 5,
                },
            },
            "issue_policies": {
                "OOMKilled": {
                    "action": "immediate_remediation",
                    "strategy": "increase_resources",
                    "confidence_threshold": 0.7,
                    "max_retries": 2,
                    "priority": 90,
                    "workflow": "oom_recovery",
                },
                "CrashLoopBackOff": {
                    "action": "delay_and_retry",
                    "strategy": "restart_pod",
                    "confidence_threshold": 0.65,
                    "max_retries": 4,
                    "priority": 80,
                    "workflow": "crash_recovery",
                    "delay_seconds": 10,
                },
                "ImagePullBackOff": {
                    "action": "escalate",
                    "strategy": "rollback_deployment",
                    "confidence_threshold": 0.8,
                    "max_retries": 1,
                    "priority": 70,
                    "workflow": "image_recovery",
                },
                "PodPending": {
                    "action": "manual_review",
                    "strategy": "no_action",
                    "confidence_threshold": 0.9,
                    "max_retries": 0,
                    "priority": 40,
                    "workflow": "scheduling_recovery",
                },
            },
            "workflows": {
                "default": {
                    "name": "default",
                    "steps": [
                        {
                            "name": "restart_pod",
                            "strategy": "restart_pod",
                            "delay_seconds": 0,
                            "max_retries": 2,
                            "stop_on_success": True,
                        },
                        {
                            "name": "scale_up",
                            "strategy": "scale_up",
                            "delay_seconds": 15,
                            "max_retries": 1,
                            "stop_on_success": True,
                        },
                    ],
                },
                "oom_recovery": {
                    "name": "oom_recovery",
                    "steps": [
                        {
                            "name": "increase_resources",
                            "strategy": "increase_resources",
                            "delay_seconds": 0,
                            "max_retries": 2,
                            "stop_on_success": True,
                        },
                        {
                            "name": "scale_up",
                            "strategy": "scale_up",
                            "delay_seconds": 30,
                            "max_retries": 1,
                            "stop_on_success": True,
                        },
                    ],
                },
                "crash_recovery": {
                    "name": "crash_recovery",
                    "steps": [
                        {
                            "name": "restart_pod",
                            "strategy": "restart_pod",
                            "delay_seconds": 0,
                            "max_retries": 2,
                            "stop_on_success": True,
                        },
                        {
                            "name": "scale_up",
                            "strategy": "scale_up",
                            "delay_seconds": 15,
                            "max_retries": 2,
                            "stop_on_success": True,
                        },
                        {
                            "name": "rollback_deployment",
                            "strategy": "rollback_deployment",
                            "delay_seconds": 30,
                            "max_retries": 1,
                            "stop_on_success": True,
                        },
                    ],
                },
                "image_recovery": {
                    "name": "image_recovery",
                    "steps": [
                        {
                            "name": "rollback_deployment",
                            "strategy": "rollback_deployment",
                            "delay_seconds": 0,
                            "max_retries": 1,
                            "stop_on_success": True,
                        }
                    ],
                },
                "scheduling_recovery": {
                    "name": "scheduling_recovery",
                    "steps": [
                        {
                            "name": "evict_pod",
                            "strategy": "evict_pod",
                            "delay_seconds": 30,
                            "max_retries": 1,
                            "stop_on_success": True,
                        }
                    ],
                },
            },
        }