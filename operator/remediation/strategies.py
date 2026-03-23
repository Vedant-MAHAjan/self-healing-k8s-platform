"""
Individual remediation strategy implementations.
Each strategy is a function that takes a diagnosis and executes the fix.
"""

import structlog
from kubernetes import client
from kubernetes.client.rest import ApiException

from healing_operator.config import Settings
from healing_operator.models import Diagnosis
from healing_operator.utils.kubernetes_helper import KubernetesHelper


logger = structlog.get_logger()


async def restart_pod_strategy(
    diagnosis: Diagnosis,
    k8s_helper: KubernetesHelper,
    settings: Settings,
    dry_run: bool = False,
) -> bool:
    """
    Restart a pod by deleting it (will be recreated by controller).
    
    Args:
        diagnosis: The diagnosis containing the issue
        k8s_helper: Kubernetes helper instance
        settings: Operator settings
        dry_run: If True, only log without executing
        
    Returns:
        True if successful
    """
    issue = diagnosis.issue
    namespace = issue.resource_namespace
    pod_name = issue.resource_name
    
    logger.info(
        "executing_pod_restart",
        namespace=namespace,
        pod=pod_name,
        dry_run=dry_run,
        reasoning=diagnosis.reasoning,
    )
    
    if dry_run:
        logger.info("dry_run_pod_restart_skipped")
        return True
    
    try:
        await k8s_helper.delete_pod(namespace, pod_name)
        
        logger.info(
            "pod_restart_successful",
            namespace=namespace,
            pod=pod_name,
        )
        return True
    
    except Exception as e:
        logger.error(
            "pod_restart_failed",
            namespace=namespace,
            pod=pod_name,
            error=str(e),
        )
        return False


async def scale_up_strategy(
    diagnosis: Diagnosis,
    k8s_helper: KubernetesHelper,
    settings: Settings,
    dry_run: bool = False,
) -> bool:
    """
    Scale up a deployment by increasing replicas.
    
    Args:
        diagnosis: The diagnosis containing the issue
        k8s_helper: Kubernetes helper instance
        settings: Operator settings
        dry_run: If True, only log without executing
        
    Returns:
        True if successful
    """
    issue = diagnosis.issue
    
    # Find the deployment for this pod
    if not issue.pod_info or not issue.pod_info.labels:
        logger.error("cannot_scale_no_labels")
        return False
    
    namespace = issue.resource_namespace
    
    # Try to find deployment from pod labels
    deployment_name = await k8s_helper.get_deployment_for_pod(
        issue.resource_name,
        namespace,
    )
    
    if not deployment_name:
        logger.error("cannot_find_deployment_for_pod")
        return False
    
    logger.info(
        "executing_scale_up",
        namespace=namespace,
        deployment=deployment_name,
        dry_run=dry_run,
    )
    
    if dry_run:
        logger.info("dry_run_scale_up_skipped")
        return True
    
    try:
        # Get current replicas
        current_replicas = await k8s_helper.get_deployment_replicas(
            namespace,
            deployment_name,
        )
        
        # Increase by 1 (or 50%, whichever is larger)
        new_replicas = max(current_replicas + 1, int(current_replicas * 1.5))
        
        await k8s_helper.scale_deployment(
            namespace,
            deployment_name,
            new_replicas,
        )
        
        logger.info(
            "scale_up_successful",
            namespace=namespace,
            deployment=deployment_name,
            old_replicas=current_replicas,
            new_replicas=new_replicas,
        )
        return True
    
    except Exception as e:
        logger.error(
            "scale_up_failed",
            namespace=namespace,
            deployment=deployment_name,
            error=str(e),
        )
        return False


async def scale_down_strategy(
    diagnosis: Diagnosis,
    k8s_helper: KubernetesHelper,
    settings: Settings,
    dry_run: bool = False,
) -> bool:
    """
    Scale down a deployment by decreasing replicas.
    """
    issue = diagnosis.issue
    namespace = issue.resource_namespace
    
    deployment_name = await k8s_helper.get_deployment_for_pod(
        issue.resource_name,
        namespace,
    )
    
    if not deployment_name:
        logger.error("cannot_find_deployment_for_pod")
        return False
    
    logger.info(
        "executing_scale_down",
        namespace=namespace,
        deployment=deployment_name,
        dry_run=dry_run,
    )
    
    if dry_run:
        logger.info("dry_run_scale_down_skipped")
        return True
    
    try:
        current_replicas = await k8s_helper.get_deployment_replicas(
            namespace,
            deployment_name,
        )
        
        # Decrease by 1, but keep at least 1
        new_replicas = max(1, current_replicas - 1)
        
        if new_replicas == current_replicas:
            logger.warning("already_at_minimum_replicas")
            return True
        
        await k8s_helper.scale_deployment(
            namespace,
            deployment_name,
            new_replicas,
        )
        
        logger.info(
            "scale_down_successful",
            namespace=namespace,
            deployment=deployment_name,
            old_replicas=current_replicas,
            new_replicas=new_replicas,
        )
        return True
    
    except Exception as e:
        logger.error(
            "scale_down_failed",
            error=str(e),
        )
        return False


async def rollback_deployment_strategy(
    diagnosis: Diagnosis,
    k8s_helper: KubernetesHelper,
    settings: Settings,
    dry_run: bool = False,
) -> bool:
    """
    Rollback a deployment to the previous revision.
    """
    issue = diagnosis.issue
    namespace = issue.resource_namespace
    
    deployment_name = await k8s_helper.get_deployment_for_pod(
        issue.resource_name,
        namespace,
    )
    
    if not deployment_name:
        # If we can't find deployment from pod, check if issue is about deployment
        if issue.deployment_info:
            deployment_name = issue.deployment_info.name
        else:
            logger.error("cannot_find_deployment")
            return False
    
    logger.info(
        "executing_rollback",
        namespace=namespace,
        deployment=deployment_name,
        dry_run=dry_run,
    )
    
    if dry_run:
        logger.info("dry_run_rollback_skipped")
        return True
    
    try:
        await k8s_helper.rollback_deployment(namespace, deployment_name)
        
        logger.info(
            "rollback_successful",
            namespace=namespace,
            deployment=deployment_name,
        )
        return True
    
    except Exception as e:
        logger.error(
            "rollback_failed",
            namespace=namespace,
            deployment=deployment_name,
            error=str(e),
        )
        return False


async def increase_resources_strategy(
    diagnosis: Diagnosis,
    k8s_helper: KubernetesHelper,
    settings: Settings,
    dry_run: bool = False,
) -> bool:
    """
    Increase resource limits for a deployment.
    Typically used for OOMKilled issues.
    """
    issue = diagnosis.issue
    namespace = issue.resource_namespace
    
    deployment_name = await k8s_helper.get_deployment_for_pod(
        issue.resource_name,
        namespace,
    )
    
    if not deployment_name:
        logger.error("cannot_find_deployment")
        return False
    
    logger.info(
        "executing_increase_resources",
        namespace=namespace,
        deployment=deployment_name,
        dry_run=dry_run,
    )
    
    if dry_run:
        logger.info("dry_run_increase_resources_skipped")
        return True
    
    try:
        # For OOMKilled, increase memory limit by 50%
        multiplier = 1.5
        
        await k8s_helper.increase_deployment_resources(
            namespace,
            deployment_name,
            memory_multiplier=multiplier,
        )
        
        logger.info(
            "increase_resources_successful",
            namespace=namespace,
            deployment=deployment_name,
            multiplier=multiplier,
        )
        return True
    
    except Exception as e:
        logger.error(
            "increase_resources_failed",
            error=str(e),
        )
        return False


async def evict_pod_strategy(
    diagnosis: Diagnosis,
    k8s_helper: KubernetesHelper,
    settings: Settings,
    dry_run: bool = False,
) -> bool:
    """
    Evict a pod (graceful termination with rescheduling).
    """
    issue = diagnosis.issue
    namespace = issue.resource_namespace
    pod_name = issue.resource_name
    
    logger.info(
        "executing_pod_eviction",
        namespace=namespace,
        pod=pod_name,
        dry_run=dry_run,
    )
    
    if dry_run:
        logger.info("dry_run_eviction_skipped")
        return True
    
    try:
        await k8s_helper.evict_pod(namespace, pod_name)
        
        logger.info(
            "pod_eviction_successful",
            namespace=namespace,
            pod=pod_name,
        )
        return True
    
    except Exception as e:
        logger.error(
            "pod_eviction_failed",
            namespace=namespace,
            pod=pod_name,
            error=str(e),
        )
        return False
