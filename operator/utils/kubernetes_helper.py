"""
Kubernetes helper utilities.
Provides convenience methods for interacting with Kubernetes API.
"""

import asyncio
import structlog
from typing import List, Optional, Dict
from kubernetes import client
from kubernetes.client.rest import ApiException
from datetime import datetime

from healing_operator.models import PodInfo, DeploymentInfo


logger = structlog.get_logger()


class KubernetesHelper:
    """Helper class for Kubernetes operations."""
    
    def __init__(self):
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.policy_v1 = client.PolicyV1Api()
    
    # Pod operations
    
    async def get_pod_info(self, name: str, namespace: str) -> Optional[PodInfo]:
        """Get pod information."""
        try:
            pod = await asyncio.to_thread(
                self.core_v1.read_namespaced_pod,
                name=name,
                namespace=namespace,
            )
            
            return PodInfo(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                uid=pod.metadata.uid,
                status=pod.status.phase,
                restart_count=sum(
                    cs.restart_count for cs in (pod.status.container_statuses or [])
                ),
                container_statuses=[
                    {
                        'name': cs.name,
                        'ready': cs.ready,
                        'restartCount': cs.restart_count,
                        'state': self._container_state_to_dict(cs.state),
                        'lastState': self._container_state_to_dict(cs.last_state),
                    }
                    for cs in (pod.status.container_statuses or [])
                ],
                node_name=pod.spec.node_name,
                labels=pod.metadata.labels or {},
                annotations=pod.metadata.annotations or {},
                creation_timestamp=pod.metadata.creation_timestamp,
            )
        
        except ApiException as e:
            logger.error(
                "failed_to_get_pod_info",
                namespace=namespace,
                pod=name,
                error=str(e),
            )
            return None
    
    def _container_state_to_dict(self, state) -> dict:
        """Convert container state to dict."""
        if not state:
            return {}
        
        result = {}
        if state.running:
            result['running'] = {
                'startedAt': str(state.running.started_at) if state.running.started_at else None
            }
        if state.waiting:
            result['waiting'] = {
                'reason': state.waiting.reason,
                'message': state.waiting.message,
            }
        if state.terminated:
            result['terminated'] = {
                'exitCode': state.terminated.exit_code,
                'reason': state.terminated.reason,
                'message': state.terminated.message,
                'startedAt': str(state.terminated.started_at) if state.terminated.started_at else None,
                'finishedAt': str(state.terminated.finished_at) if state.terminated.finished_at else None,
            }
        return result
    
    async def get_pod_logs(
        self,
        name: str,
        namespace: str,
        max_lines: int = 500,
        container: Optional[str] = None,
    ) -> List[str]:
        """Get pod logs."""
        try:
            logs = await asyncio.to_thread(
                self.core_v1.read_namespaced_pod_log,
                name=name,
                namespace=namespace,
                container=container,
                tail_lines=max_lines,
            )
            
            return logs.split('\n')
        
        except ApiException as e:
            logger.warning(
                "failed_to_get_pod_logs",
                namespace=namespace,
                pod=name,
                error=str(e),
            )
            return []
    
    async def get_pod_events(
        self,
        pod_name: str,
        namespace: str,
        max_events: int = 100,
    ) -> List[Dict]:
        """Get events for a pod."""
        try:
            events = await asyncio.to_thread(
                self.core_v1.list_namespaced_event,
                namespace=namespace,
                field_selector=f'involvedObject.name={pod_name}',
            )
            
            event_list = []
            for event in events.items[:max_events]:
                event_list.append({
                    'type': event.type,
                    'reason': event.reason,
                    'message': event.message,
                    'count': event.count,
                    'firstTimestamp': str(event.first_timestamp) if event.first_timestamp else None,
                    'lastTimestamp': str(event.last_timestamp) if event.last_timestamp else None,
                    'eventTime': str(event.event_time) if event.event_time else None,
                })
            
            return event_list
        
        except ApiException as e:
            logger.warning(
                "failed_to_get_pod_events",
                namespace=namespace,
                pod=pod_name,
                error=str(e),
            )
            return []
    
    async def delete_pod(self, namespace: str, name: str) -> bool:
        """Delete a pod."""
        try:
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_pod,
                name=name,
                namespace=namespace,
            )
            
            logger.info("pod_deleted", namespace=namespace, pod=name)
            return True
        
        except ApiException as e:
            logger.error(
                "failed_to_delete_pod",
                namespace=namespace,
                pod=name,
                error=str(e),
            )
            return False
    
    async def evict_pod(self, namespace: str, name: str) -> bool:
        """Evict a pod using the eviction API."""
        try:
            eviction = client.V1Eviction(
                metadata=client.V1ObjectMeta(
                    name=name,
                    namespace=namespace,
                )
            )
            
            await asyncio.to_thread(
                self.core_v1.create_namespaced_pod_eviction,
                name=name,
                namespace=namespace,
                body=eviction,
            )
            
            logger.info("pod_evicted", namespace=namespace, pod=name)
            return True
        
        except ApiException as e:
            logger.error(
                "failed_to_evict_pod",
                namespace=namespace,
                pod=name,
                error=str(e),
            )
            return False
    
    # Deployment operations
    
    async def get_deployment_for_pod(
        self,
        pod_name: str,
        namespace: str,
    ) -> Optional[str]:
        """Find the deployment that owns a pod."""
        try:
            pod = await asyncio.to_thread(
                self.core_v1.read_namespaced_pod,
                name=pod_name,
                namespace=namespace,
            )
            
            # Check owner references
            if pod.metadata.owner_references:
                for owner in pod.metadata.owner_references:
                    if owner.kind == 'ReplicaSet':
                        # Get the ReplicaSet
                        rs = await asyncio.to_thread(
                            self.apps_v1.read_namespaced_replica_set,
                            name=owner.name,
                            namespace=namespace,
                        )
                        
                        # Get the Deployment from ReplicaSet's owner
                        if rs.metadata.owner_references:
                            for rs_owner in rs.metadata.owner_references:
                                if rs_owner.kind == 'Deployment':
                                    return rs_owner.name
            
            return None
        
        except ApiException as e:
            logger.error(
                "failed_to_find_deployment",
                namespace=namespace,
                pod=pod_name,
                error=str(e),
            )
            return None
    
    async def get_deployment_replicas(
        self,
        namespace: str,
        name: str,
    ) -> int:
        """Get current replica count for a deployment."""
        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment,
                name=name,
                namespace=namespace,
            )
            
            return deployment.spec.replicas or 0
        
        except ApiException as e:
            logger.error(
                "failed_to_get_deployment_replicas",
                namespace=namespace,
                deployment=name,
                error=str(e),
            )
            return 0
    
    async def scale_deployment(
        self,
        namespace: str,
        name: str,
        replicas: int,
    ) -> bool:
        """Scale a deployment."""
        try:
            # Patch the deployment
            body = {
                'spec': {
                    'replicas': replicas
                }
            }
            
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment_scale,
                name=name,
                namespace=namespace,
                body=body,
            )
            
            logger.info(
                "deployment_scaled",
                namespace=namespace,
                deployment=name,
                replicas=replicas,
            )
            return True
        
        except ApiException as e:
            logger.error(
                "failed_to_scale_deployment",
                namespace=namespace,
                deployment=name,
                error=str(e),
            )
            return False
    
    async def rollback_deployment(
        self,
        namespace: str,
        name: str,
        revision: Optional[int] = None,
    ) -> bool:
        """Rollback a deployment to a previous revision."""
        try:
            # If no revision specified, rollback to previous
            if not revision:
                # Get current revision
                deployment = await asyncio.to_thread(
                    self.apps_v1.read_namespaced_deployment,
                    name=name,
                    namespace=namespace,
                )
                
                current_revision = deployment.metadata.annotations.get(
                    'deployment.kubernetes.io/revision'
                )
                
                if current_revision:
                    revision = int(current_revision) - 1
            
            # Perform rollback using kubectl rollout undo
            # For now, we'll trigger it by updating the deployment
            # In production, you might want to use kubectl directly
            
            # Get the previous ReplicaSet
            rs_list = await asyncio.to_thread(
                self.apps_v1.list_namespaced_replica_set,
                namespace=namespace,
                label_selector=f'app={name}',  # Adjust based on your labels
            )
            
            # Sort by revision
            sorted_rs = sorted(
                rs_list.items,
                key=lambda rs: int(
                    rs.metadata.annotations.get('deployment.kubernetes.io/revision', '0')
                ),
                reverse=True,
            )
            
            if len(sorted_rs) >= 2:
                # Get the previous revision template
                previous_rs = sorted_rs[1]
                
                # Update deployment with previous template
                deployment = await asyncio.to_thread(
                    self.apps_v1.read_namespaced_deployment,
                    name=name,
                    namespace=namespace,
                )
                
                deployment.spec.template = previous_rs.spec.template
                
                await asyncio.to_thread(
                    self.apps_v1.patch_namespaced_deployment,
                    name=name,
                    namespace=namespace,
                    body=deployment,
                )
                
                logger.info(
                    "deployment_rolled_back",
                    namespace=namespace,
                    deployment=name,
                )
                return True
            else:
                logger.warning(
                    "no_previous_revision_found",
                    namespace=namespace,
                    deployment=name,
                )
                return False
        
        except ApiException as e:
            logger.error(
                "failed_to_rollback_deployment",
                namespace=namespace,
                deployment=name,
                error=str(e),
            )
            return False
    
    async def increase_deployment_resources(
        self,
        namespace: str,
        name: str,
        cpu_multiplier: float = 1.0,
        memory_multiplier: float = 1.0,
    ) -> bool:
        """Increase resource limits for a deployment."""
        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment,
                name=name,
                namespace=namespace,
            )
            
            # Update container resources
            for container in deployment.spec.template.spec.containers:
                if container.resources and container.resources.limits:
                    limits = container.resources.limits
                    
                    # Increase memory
                    if 'memory' in limits and memory_multiplier != 1.0:
                        current_mem = limits['memory']
                        # Parse memory value (e.g., "256Mi", "1Gi")
                        import re
                        match = re.match(r'(\d+)([MGT]i?)', current_mem)
                        if match:
                            value = int(match.group(1))
                            unit = match.group(2)
                            new_value = int(value * memory_multiplier)
                            limits['memory'] = f"{new_value}{unit}"
                    
                    # Increase CPU if needed
                    if 'cpu' in limits and cpu_multiplier != 1.0:
                        current_cpu = limits['cpu']
                        # Parse CPU value (e.g., "500m", "1")
                        if current_cpu.endswith('m'):
                            value = int(current_cpu[:-1])
                            new_value = int(value * cpu_multiplier)
                            limits['cpu'] = f"{new_value}m"
                        else:
                            value = float(current_cpu)
                            new_value = value * cpu_multiplier
                            limits['cpu'] = str(new_value)
            
            # Apply the update
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment,
                name=name,
                namespace=namespace,
                body=deployment,
            )
            
            logger.info(
                "deployment_resources_increased",
                namespace=namespace,
                deployment=name,
                cpu_multiplier=cpu_multiplier,
                memory_multiplier=memory_multiplier,
            )
            return True
        
        except Exception as e:
            logger.error(
                "failed_to_increase_deployment_resources",
                namespace=namespace,
                deployment=name,
                error=str(e),
            )
            return False
