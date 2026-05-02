"""
Data models for the self-healing operator.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class IssueType(Enum):
    """Types of issues the operator can handle."""
    CRASH_LOOP_BACKOFF = "CrashLoopBackOff"
    IMAGE_PULL_BACKOFF = "ImagePullBackOff"
    OOM_KILLED = "OOMKilled"
    MEMORY_LEAK = "MemoryLeak"
    CPU_THROTTLING = "CPUThrottling"
    HEALTH_CHECK_FAILURE = "HealthCheckFailure"
    NODE_PRESSURE = "NodePressure"
    PENDING_POD = "PodPending"
    UNKNOWN = "Unknown"


class RemediationStrategy(Enum):
    """Available remediation strategies."""
    RESTART_POD = "restart_pod"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    INCREASE_RESOURCES = "increase_resources"
    EVICT_POD = "evict_pod"
    NO_ACTION = "no_action"
    MANUAL_INTERVENTION = "manual_intervention"


class RemediationStatus(Enum):
    """Status of a remediation attempt."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PodInfo:
    """Information about a pod."""
    name: str
    namespace: str
    uid: str
    status: str
    restart_count: int
    container_statuses: List[Dict]
    node_name: Optional[str] = None
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    creation_timestamp: Optional[datetime] = None


@dataclass
class DeploymentInfo:
    """Information about a deployment."""
    name: str
    namespace: str
    uid: str
    replicas: int
    ready_replicas: int
    available_replicas: int
    labels: Dict[str, str] = field(default_factory=dict)
    selector: Dict[str, str] = field(default_factory=dict)
    revision: Optional[str] = None


@dataclass
class Issue:
    """Represents a detected issue in the cluster."""
    issue_id: str
    issue_type: IssueType
    resource_kind: str
    resource_name: str
    resource_namespace: str
    description: str
    severity: str  # critical, high, medium, low
    detected_at: datetime
    pod_info: Optional[PodInfo] = None
    deployment_info: Optional[DeploymentInfo] = None
    logs: List[str] = field(default_factory=list)
    events: List[Dict] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    alert_labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class Diagnosis:
    """AI-generated diagnosis of an issue."""
    issue: Issue
    root_cause: str
    analysis: str
    recommended_strategy: RemediationStrategy
    confidence: float  # 0.0 to 1.0
    reasoning: str
    alternative_strategies: List[RemediationStrategy] = field(default_factory=list)
    requires_manual_intervention: bool = False
    suggested_actions: List[str] = field(default_factory=list)


@dataclass
class RemediationAction:
    """Represents a remediation action to be taken."""
    action_id: str
    diagnosis: Diagnosis
    strategy: RemediationStrategy
    status: RemediationStatus
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    applied_by: str = "self-healing-operator"
    dry_run: bool = False
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class Alert:
    """Prometheus alert received by the operator."""
    alert_name: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    starts_at: datetime
    status: str  # firing, resolved
    ends_at: Optional[datetime] = None
    generator_url: Optional[str] = None
    fingerprint: Optional[str] = None
