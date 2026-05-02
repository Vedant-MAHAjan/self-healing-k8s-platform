"""
Prometheus alert handlers for the self-healing operator.
Receives and processes alerts from Alertmanager.
"""

import asyncio
import structlog
from aiohttp import web
from datetime import datetime
from typing import List, Optional

from ..models import Alert, Issue, IssueType
from ..utils.kubernetes_helper import KubernetesHelper


logger = structlog.get_logger()


class AlertReceiver:
    """
    HTTP server to receive Prometheus alerts from Alertmanager.
    Webhook endpoint for Alertmanager.
    """
    
    def __init__(self, memo: dict, port: int = 9099):
        self.memo = memo
        self.port = port
        self.app = web.Application()
        self.app.router.add_post('/alerts', self.handle_alerts)
        self.app.router.add_get('/health', self.health_check)
        self.runner = None
    
    async def start(self):
        """Start the alert receiver HTTP server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await site.start()
        logger.info("alert_receiver_started", port=self.port)
    
    async def stop(self):
        """Stop the alert receiver."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("alert_receiver_stopped")
    
    async def health_check(self, request):
        """Health check endpoint."""
        return web.json_response({"status": "healthy"})
    
    async def handle_alerts(self, request):
        """
        Handle incoming alerts from Alertmanager.
        
        Expected payload format:
        {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {...},
                    "annotations": {...},
                    "startsAt": "...",
                    "endsAt": "...",
                    "generatorURL": "...",
                    "fingerprint": "..."
                }
            ]
        }
        """
        try:
            data = await request.json()
            alerts = data.get('alerts', [])
            
            logger.info("received_alerts", count=len(alerts))
            
            for alert_data in alerts:
                alert = self._parse_alert(alert_data)
                
                # Only process firing alerts
                if alert.status == 'firing':
                    await self._process_alert(alert)
            
            return web.json_response({"status": "ok", "processed": len(alerts)})
        
        except Exception as e:
            logger.error("alert_processing_error", error=str(e), exc_info=True)
            return web.json_response(
                {"status": "error", "message": str(e)},
                status=500
            )
    
    def _parse_alert(self, alert_data: dict) -> Alert:
        """Parse alert data into Alert model."""
        return Alert(
            alert_name=alert_data.get('labels', {}).get('alertname', 'Unknown'),
            labels=alert_data.get('labels', {}),
            annotations=alert_data.get('annotations', {}),
            starts_at=datetime.fromisoformat(
                alert_data.get('startsAt', '').replace('Z', '+00:00')
            ),
            ends_at=datetime.fromisoformat(
                alert_data.get('endsAt', '').replace('Z', '+00:00')
            ) if alert_data.get('endsAt') else None,
            status=alert_data.get('status', 'unknown'),
            generator_url=alert_data.get('generatorURL'),
            fingerprint=alert_data.get('fingerprint'),
        )
    
    async def _process_alert(self, alert: Alert):
        """Process a firing alert and convert it to an issue."""
        logger.info(
            "processing_alert",
            alert_name=alert.alert_name,
            namespace=alert.labels.get('namespace'),
            pod=alert.labels.get('pod'),
        )
        
        # Convert alert to issue based on alert name
        issue = await self._alert_to_issue(alert)
        
        if issue:
            # Import here to avoid circular dependency
            from .pod_handlers import handle_issue
            await handle_issue(issue, self.memo)
    
    async def _alert_to_issue(self, alert: Alert) -> Optional[Issue]:
        """
        Convert a Prometheus alert to an Issue.
        Maps common alerts to issue types.
        """
        alert_name = alert.alert_name
        labels = alert.labels
        annotations = alert.annotations
        
        namespace = labels.get('namespace', 'default')
        pod_name = labels.get('pod')
        
        if not pod_name:
            logger.warning("alert_missing_pod_label", alert_name=alert_name)
            return None
        
        # Map alert names to issue types
        issue_type_mapping = {
            'KubePodCrashLooping': IssueType.CRASH_LOOP_BACKOFF,
            'KubePodNotReady': IssueType.HEALTH_CHECK_FAILURE,
            'KubeContainerOOMKilled': IssueType.OOM_KILLED,
            'KubePodImagePullBackOff': IssueType.IMAGE_PULL_BACKOFF,
            'HighMemoryUsage': IssueType.MEMORY_LEAK,
            'CPUThrottlingHigh': IssueType.CPU_THROTTLING,
        }
        
        issue_type = issue_type_mapping.get(alert_name, IssueType.UNKNOWN)
        
        # Fetch pod info
        k8s_helper = KubernetesHelper()
        try:
            pod_info = await k8s_helper.get_pod_info(pod_name, namespace)
        except Exception as e:
            logger.error(
                "failed_to_fetch_pod_info",
                pod=pod_name,
                namespace=namespace,
                error=str(e),
            )
            return None
        
        return Issue(
            issue_id=f"{namespace}-{pod_name}-alert-{alert.fingerprint[:8]}",
            issue_type=issue_type,
            resource_kind='Pod',
            resource_name=pod_name,
            resource_namespace=namespace,
            description=annotations.get('description', annotations.get('summary', alert_name)),
            severity=labels.get('severity', 'medium'),
            detected_at=alert.starts_at,
            pod_info=pod_info,
            alert_labels=labels,
        )


# Global alert receiver instance
alert_receiver_instance = None


async def start_alert_receiver(memo: dict):
    """Start the alert receiver service."""
    global alert_receiver_instance
    
    if alert_receiver_instance is None:
        alert_receiver_instance = AlertReceiver(memo)
        await alert_receiver_instance.start()


async def stop_alert_receiver():
    """Stop the alert receiver service."""
    global alert_receiver_instance
    
    if alert_receiver_instance:
        await alert_receiver_instance.stop()
        alert_receiver_instance = None
