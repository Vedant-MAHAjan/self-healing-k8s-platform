"""
Pod event handlers for the self-healing operator.
Monitors pod events and triggers remediation when issues are detected.
"""

import kopf
import structlog
from datetime import datetime
from typing import Optional
from kubernetes import client

from ..models import Issue, IssueType, PodInfo
from ..utils.kubernetes_helper import KubernetesHelper
from ..utils.metrics import (
    alerts_received_counter,
    fixes_applied_counter,
    fixes_failed_counter,
)


logger = structlog.get_logger()


@kopf.on.event('v1', 'pods')
async def pod_event_handler(event, memo, **kwargs):
    """
    Handle pod events and detect issues.
    Triggered on any pod state change.
    """
    pod = event['object']
    event_type = event['type']
    
    namespace = pod['metadata']['namespace']
    name = pod['metadata']['name']
    
    # Skip system namespaces unless configured otherwise
    if namespace in ['kube-system', 'kube-public', 'kube-node-lease']:
        return
    
    # Skip the operator's own namespace to avoid self-remediation
    settings = memo.get('settings')
    if settings and namespace == settings.operator_namespace:
        return
    
    logger.debug(
        "pod_event",
        event_type=event_type,
        namespace=namespace,
        name=name,
        phase=pod.get('status', {}).get('phase'),
    )
    
    # Check for issues
    issue = await detect_pod_issue(pod, memo)
    
    if issue:
        logger.info(
            "pod_issue_detected",
            issue_type=issue.issue_type.value,
            namespace=namespace,
            name=name,
        )
        
        alerts_received_counter.labels(
            issue_type=issue.issue_type.value,
            namespace=namespace,
        ).inc()
        
        # Trigger diagnosis and remediation
        await handle_issue(issue, memo)


async def detect_pod_issue(pod: dict, memo: dict) -> Optional[Issue]:
    """
    Analyze pod status and detect issues.
    
    Returns:
        Issue object if an issue is detected, None otherwise
    """
    metadata = pod['metadata']
    status = pod.get('status', {})
    spec = pod.get('spec', {})
    
    namespace = metadata['namespace']
    name = metadata['name']
    uid = metadata['uid']
    
    container_statuses = status.get('containerStatuses', [])
    phase = status.get('phase')
    
    # Build PodInfo
    pod_info = PodInfo(
        name=name,
        namespace=namespace,
        uid=uid,
        status=phase,
        restart_count=sum(cs.get('restartCount', 0) for cs in container_statuses),
        container_statuses=container_statuses,
        node_name=spec.get('nodeName'),
        labels=metadata.get('labels', {}),
        annotations=metadata.get('annotations', {}),
        creation_timestamp=metadata.get('creationTimestamp'),
    )
    
    # Detect CrashLoopBackOff
    for container_status in container_statuses:
        waiting = container_status.get('state', {}).get('waiting', {})
        reason = waiting.get('reason', '')
        
        if reason == 'CrashLoopBackOff':
            return Issue(
                issue_id=f"{namespace}-{name}-crash-{uid[:8]}",
                issue_type=IssueType.CRASH_LOOP_BACKOFF,
                resource_kind='Pod',
                resource_name=name,
                resource_namespace=namespace,
                description=f"Pod {name} is in CrashLoopBackOff state",
                severity='high',
                detected_at=datetime.utcnow(),
                pod_info=pod_info,
            )
        
        if reason == 'ImagePullBackOff' or reason == 'ErrImagePull':
            return Issue(
                issue_id=f"{namespace}-{name}-image-{uid[:8]}",
                issue_type=IssueType.IMAGE_PULL_BACKOFF,
                resource_kind='Pod',
                resource_name=name,
                resource_namespace=namespace,
                description=f"Pod {name} cannot pull image: {waiting.get('message', '')}",
                severity='high',
                detected_at=datetime.utcnow(),
                pod_info=pod_info,
            )
        
        # Check for OOMKilled
        terminated = container_status.get('lastState', {}).get('terminated', {})
        if terminated.get('reason') == 'OOMKilled':
            return Issue(
                issue_id=f"{namespace}-{name}-oom-{uid[:8]}",
                issue_type=IssueType.OOM_KILLED,
                resource_kind='Pod',
                resource_name=name,
                resource_namespace=namespace,
                description=f"Pod {name} was OOMKilled",
                severity='critical',
                detected_at=datetime.utcnow(),
                pod_info=pod_info,
            )
    
    # Check for pending pods
    if phase == 'Pending':
        conditions = status.get('conditions', [])
        unschedulable = any(
            c.get('reason') == 'Unschedulable' 
            for c in conditions 
            if c.get('type') == 'PodScheduled' and c.get('status') == 'False'
        )
        
        if unschedulable:
            return Issue(
                issue_id=f"{namespace}-{name}-pending-{uid[:8]}",
                issue_type=IssueType.PENDING_POD,
                resource_kind='Pod',
                resource_name=name,
                resource_namespace=namespace,
                description=f"Pod {name} is pending (unschedulable)",
                severity='medium',
                detected_at=datetime.utcnow(),
                pod_info=pod_info,
            )
    
    return None


async def handle_issue(issue: Issue, memo: dict):
    """
    Handle a detected issue by triggering diagnosis and remediation.
    """
    settings = memo.get('settings')
    ai_engine = memo.get('ai_engine')
    strategy_manager = memo.get('strategy_manager')
    control_plane = memo.get('control_plane')
    
    if control_plane:
        try:
            await control_plane.process_issue(issue)
            return
        except Exception as exc:
            logger.error(
                "autonomous_control_plane_failed",
                issue_id=issue.issue_id,
                error=str(exc),
                exc_info=True,
            )

    if not settings or not ai_engine or not strategy_manager:
        logger.warning(
            "memo_not_initialized",
            message="Settings, AI engine, or strategy manager not available in memo",
        )
        return
    
    try:
        # Enrich issue with logs and events
        k8s_helper = KubernetesHelper()
        issue.logs = await k8s_helper.get_pod_logs(
            issue.resource_name,
            issue.resource_namespace,
            max_lines=settings.max_log_lines,
        )
        issue.events = await k8s_helper.get_pod_events(
            issue.resource_name,
            issue.resource_namespace,
            max_events=settings.max_events_lookback,
        )
        
        # Get AI diagnosis
        logger.info("requesting_ai_diagnosis", issue_id=issue.issue_id)
        diagnosis = await ai_engine.diagnose(issue)
        
        logger.info(
            "ai_diagnosis_complete",
            issue_id=issue.issue_id,
            strategy=diagnosis.recommended_strategy.value,
            confidence=diagnosis.confidence,
        )
        
        # Execute remediation strategy
        if settings.auto_approve_fixes or diagnosis.confidence > 0.8:
            logger.info(
                "executing_remediation",
                issue_id=issue.issue_id,
                strategy=diagnosis.recommended_strategy.value,
            )
            
            success = await strategy_manager.execute(diagnosis, dry_run=settings.dry_run)
            
            if success:
                fixes_applied_counter.labels(
                    strategy=diagnosis.recommended_strategy.value,
                    namespace=issue.resource_namespace,
                ).inc()
                logger.info("remediation_successful", issue_id=issue.issue_id)
            else:
                fixes_failed_counter.labels(
                    strategy=diagnosis.recommended_strategy.value,
                    namespace=issue.resource_namespace,
                ).inc()
                logger.error("remediation_failed", issue_id=issue.issue_id)
        else:
            logger.info(
                "remediation_requires_approval",
                issue_id=issue.issue_id,
                confidence=diagnosis.confidence,
            )
    
    except Exception as e:
        logger.error(
            "issue_handling_failed",
            issue_id=issue.issue_id,
            error=str(e),
            exc_info=True,
        )
