"""Workflow engine for multi-step remediation orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from ..config_manager import ConfigManager, IssuePolicy, WorkflowConfig, WorkflowStepConfig
from ..decision_engine import ControlDecision
from ..models import Diagnosis, Issue, RemediationStrategy


logger = structlog.get_logger()


@dataclass
class WorkflowStep:
    name: str
    strategy: str
    delay_seconds: int = 0
    max_retries: int = 1
    stop_on_success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "strategy": self.strategy,
            "delay_seconds": self.delay_seconds,
            "max_retries": self.max_retries,
            "stop_on_success": self.stop_on_success,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WorkflowStep":
        return cls(
            name=payload["name"],
            strategy=payload["strategy"],
            delay_seconds=int(payload.get("delay_seconds", 0)),
            max_retries=int(payload.get("max_retries", 1)),
            stop_on_success=bool(payload.get("stop_on_success", True)),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass
class WorkflowPlan:
    workflow_name: str
    steps: List[WorkflowStep]
    current_step_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "current_step_index": self.current_step_index,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WorkflowPlan":
        return cls(
            workflow_name=payload["workflow_name"],
            current_step_index=int(payload.get("current_step_index", 0)),
            metadata=dict(payload.get("metadata", {})),
            steps=[WorkflowStep.from_dict(step) for step in payload.get("steps", [])],
        )


class WorkflowEngine:
    """Construct workflow plans from policies and decisions."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def build_plan(
        self,
        issue: Issue,
        diagnosis: Diagnosis,
        decision: ControlDecision,
    ) -> WorkflowPlan:
        workflow_name = decision.workflow_name or "default"
        workflow_config = self.config_manager.get_workflow(workflow_name)

        if workflow_config and workflow_config.steps:
            steps = [
                WorkflowStep(
                    name=step.name,
                    strategy=step.strategy,
                    delay_seconds=step.delay_seconds,
                    max_retries=step.max_retries,
                    stop_on_success=step.stop_on_success,
                )
                for step in workflow_config.steps
            ]
        else:
            steps = [
                WorkflowStep(
                    name=decision.strategy.value,
                    strategy=decision.strategy.value,
                    delay_seconds=decision.delay_seconds,
                    max_retries=decision.max_retries,
                    stop_on_success=True,
                )
            ]

        plan = WorkflowPlan(
            workflow_name=workflow_name,
            steps=steps,
            metadata={
                "issue_id": issue.issue_id,
                "strategy": diagnosis.recommended_strategy.value,
                "decision": decision.action.value,
            },
        )

        logger.info(
            "workflow_plan_built",
            issue_id=issue.issue_id,
            workflow=plan.workflow_name,
            steps=[step.name for step in steps],
        )
        return plan

    def build_job_payload(
        self,
        issue: Issue,
        diagnosis: Diagnosis,
        decision: ControlDecision,
        workflow: WorkflowPlan,
        step_index: int = 0,
    ) -> Dict[str, Any]:
        return {
            "issue": self._serialize_issue(issue),
            "diagnosis": self._serialize_diagnosis(diagnosis),
            "decision": decision.to_dict(),
            "workflow": workflow.to_dict(),
            "step_index": step_index,
        }

    def next_step(self, workflow: WorkflowPlan, step_index: int) -> Optional[WorkflowStep]:
        next_index = step_index + 1
        if next_index < len(workflow.steps):
            return workflow.steps[next_index]
        return None

    def get_current_step(self, workflow: WorkflowPlan) -> WorkflowStep:
        return workflow.steps[workflow.current_step_index]

    def _serialize_issue(self, issue: Issue) -> Dict[str, Any]:
        return {
            "issue_id": issue.issue_id,
            "issue_type": issue.issue_type.value,
            "resource_kind": issue.resource_kind,
            "resource_name": issue.resource_name,
            "resource_namespace": issue.resource_namespace,
            "description": issue.description,
            "severity": issue.severity,
            "detected_at": issue.detected_at.isoformat(),
            "logs": list(issue.logs),
            "events": list(issue.events),
            "metrics": dict(issue.metrics),
            "alert_labels": dict(issue.alert_labels),
            "pod_info": self._serialize_pod_info(issue.pod_info) if issue.pod_info else None,
            "deployment_info": self._serialize_deployment_info(issue.deployment_info) if issue.deployment_info else None,
        }

    def _serialize_diagnosis(self, diagnosis: Diagnosis) -> Dict[str, Any]:
        return {
            "root_cause": diagnosis.root_cause,
            "analysis": diagnosis.analysis,
            "recommended_strategy": diagnosis.recommended_strategy.value,
            "confidence": diagnosis.confidence,
            "reasoning": diagnosis.reasoning,
            "alternative_strategies": [strategy.value for strategy in diagnosis.alternative_strategies],
            "requires_manual_intervention": diagnosis.requires_manual_intervention,
            "suggested_actions": list(diagnosis.suggested_actions),
        }

    def _serialize_pod_info(self, pod_info: Any) -> Dict[str, Any]:
        creation_timestamp = pod_info.creation_timestamp
        if hasattr(creation_timestamp, "isoformat"):
            creation_timestamp = creation_timestamp.isoformat()
        elif creation_timestamp is not None:
            creation_timestamp = str(creation_timestamp)

        return {
            "name": pod_info.name,
            "namespace": pod_info.namespace,
            "uid": pod_info.uid,
            "status": pod_info.status,
            "restart_count": pod_info.restart_count,
            "container_statuses": list(pod_info.container_statuses),
            "node_name": pod_info.node_name,
            "labels": dict(pod_info.labels),
            "annotations": dict(pod_info.annotations),
            "creation_timestamp": creation_timestamp,
        }

    def _serialize_deployment_info(self, deployment_info: Any) -> Dict[str, Any]:
        return {
            "name": deployment_info.name,
            "namespace": deployment_info.namespace,
            "uid": deployment_info.uid,
            "replicas": deployment_info.replicas,
            "ready_replicas": deployment_info.ready_replicas,
            "available_replicas": deployment_info.available_replicas,
            "labels": dict(deployment_info.labels),
            "selector": dict(deployment_info.selector),
            "revision": deployment_info.revision,
        }