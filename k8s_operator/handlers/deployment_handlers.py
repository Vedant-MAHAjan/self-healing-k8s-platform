"""
Deployment event handlers for the self-healing operator.
Monitors deployment health and manages rollbacks.
"""

import kopf
import structlog
from datetime import datetime
from kubernetes import client

from ..models import Issue, IssueType, DeploymentInfo
from ..utils.kubernetes_helper import KubernetesHelper


logger = structlog.get_logger()


@kopf.on.event('apps/v1', 'deployments')
async def deployment_event_handler(event, memo, **kwargs):
    """
    Handle deployment events and detect issues.
    """
    deployment = event['object']
    event_type = event['type']
    
    namespace = deployment['metadata']['namespace']
    name = deployment['metadata']['name']
    
    # Skip system namespaces
    if namespace in ['kube-system', 'kube-public', 'kube-node-lease']:
        return
    
    settings = memo.get('settings')
    if settings and namespace == settings.operator_namespace:
        return
    
    spec = deployment.get('spec', {})
    status = deployment.get('status', {})
    
    desired_replicas = spec.get('replicas', 0)
    ready_replicas = status.get('readyReplicas', 0)
    available_replicas = status.get('availableReplicas', 0)
    
    logger.debug(
        "deployment_event",
        event_type=event_type,
        namespace=namespace,
        name=name,
        desired=desired_replicas,
        ready=ready_replicas,
    )
    
    # Detect unhealthy deployments
    if desired_replicas > 0 and ready_replicas < desired_replicas:
        # Get conditions
        conditions = status.get('conditions', [])
        progressing = next(
            (c for c in conditions if c.get('type') == 'Progressing'),
            None
        )
        
        # Check if deployment is stuck
        if progressing and progressing.get('status') == 'False':
            reason = progressing.get('reason', '')
            message = progressing.get('message', '')
            
            logger.warning(
                "deployment_not_progressing",
                namespace=namespace,
                name=name,
                reason=reason,
                message=message,
            )


@kopf.on.field('apps/v1', 'deployments', field='status.conditions')
async def deployment_condition_changed(old, new, memo, namespace, name, **kwargs):
    """
    Triggered when deployment conditions change.
    Useful for detecting failed rollouts.
    """
    settings = memo.get('settings')
    
    if not settings or not settings.enable_rollback:
        return
    
    # Check for failed deployment condition
    if new:
        for condition in new:
            if (condition.get('type') == 'Progressing' and 
                condition.get('status') == 'False' and
                condition.get('reason') == 'ProgressDeadlineExceeded'):
                
                logger.error(
                    "deployment_rollout_failed",
                    namespace=namespace,
                    name=name,
                    message=condition.get('message'),
                )
                
                # Could trigger automatic rollback here
                # await trigger_rollback(namespace, name, memo)


async def trigger_rollback(namespace: str, name: str, memo: dict):
    """Trigger a deployment rollback."""
    k8s_helper = KubernetesHelper()
    
    logger.info(
        "initiating_deployment_rollback",
        namespace=namespace,
        name=name,
    )
    
    try:
        await k8s_helper.rollback_deployment(namespace, name)
        logger.info(
            "deployment_rollback_successful",
            namespace=namespace,
            name=name,
        )
    except Exception as e:
        logger.error(
            "deployment_rollback_failed",
            namespace=namespace,
            name=name,
            error=str(e),
        )
