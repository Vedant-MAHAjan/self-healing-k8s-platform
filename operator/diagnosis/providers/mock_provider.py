"""
Mock AI provider for demo purposes.
Simulates intelligent diagnosis without requiring external API keys.
Uses rule-based analysis with realistic-looking responses.
"""

import asyncio
import json
import random
import structlog
from datetime import datetime

from healing_operator.models import Issue, IssueType


logger = structlog.get_logger()


# Simulated diagnosis templates based on issue types
DIAGNOSIS_TEMPLATES = {
    IssueType.CRASH_LOOP_BACKOFF: {
        "root_causes": [
            "Application crashes immediately after startup due to missing configuration",
            "Container fails health check and enters crash loop",
            "Startup script exits with error code, triggering restart",
            "Application throws unhandled exception during initialization",
        ],
        "analyses": [
            "The container is repeatedly crashing and being restarted by Kubernetes. Analysis of the restart pattern suggests an application-level issue rather than resource constraints. The crash occurs within seconds of container start, indicating a startup failure.",
            "Container enters CrashLoopBackOff state after multiple failed restart attempts. The exponential backoff indicates Kubernetes is throttling restart attempts. Root cause appears to be application initialization failure.",
        ],
        "strategy": "restart_pod",
        "reasoning": "Restarting the pod will give the application a fresh start. If the issue is transient (race condition, timing issue), this often resolves it. If it persists, further investigation of application logs is recommended.",
        "confidence": 0.85,
    },
    IssueType.OOM_KILLED: {
        "root_causes": [
            "Memory leak in application causing gradual memory exhaustion",
            "Application memory requirements exceed configured limits",
            "Unexpected spike in memory usage due to large data processing",
            "JVM heap size misconfigured relative to container limits",
        ],
        "analyses": [
            "Container was terminated by the OOM killer after exceeding memory limits. Memory usage pattern shows gradual increase over time, suggesting a memory leak. Current limits may be insufficient for the workload.",
            "The container exceeded its memory limit and was killed by Kubernetes. This is a critical issue that requires either increasing memory limits or investigating memory usage patterns.",
        ],
        "strategy": "increase_resources",
        "reasoning": "Increasing memory limits will prevent immediate OOM kills. This is a temporary fix - the application should be profiled to identify memory leaks. Recommended to increase limits by 50% initially.",
        "confidence": 0.90,
    },
    IssueType.IMAGE_PULL_BACKOFF: {
        "root_causes": [
            "Container image tag does not exist in registry",
            "Registry authentication credentials are invalid or expired",
            "Network connectivity issues to container registry",
            "Image was deleted or moved in the registry",
        ],
        "analyses": [
            "Kubernetes cannot pull the specified container image. The ImagePullBackOff state indicates repeated failures. This typically occurs when an image tag doesn't exist or credentials are invalid.",
            "Container image pull is failing consistently. Analysis suggests the image reference may be incorrect or the image was removed from the registry.",
        ],
        "strategy": "rollback_deployment",
        "reasoning": "Rolling back to the previous deployment version will restore a known working image. This is the safest immediate action while the image issue is investigated.",
        "confidence": 0.92,
    },
    IssueType.MEMORY_LEAK: {
        "root_causes": [
            "Application has memory leak causing gradual memory increase",
            "Connection pool not properly releasing connections",
            "Cache growing unbounded without eviction policy",
            "Event listeners or callbacks not being cleaned up",
        ],
        "analyses": [
            "Memory usage shows consistent upward trend over time without corresponding increase in workload. This pattern is characteristic of a memory leak in the application.",
            "Gradual memory consumption increase detected. The rate of increase suggests a slow leak that will eventually cause OOM. Restarting will temporarily resolve symptoms.",
        ],
        "strategy": "restart_pod",
        "reasoning": "Restarting the pod will free leaked memory and restore normal operation. This is a temporary fix - the underlying memory leak should be investigated and fixed in the application code.",
        "confidence": 0.88,
    },
    IssueType.HEALTH_CHECK_FAILURE: {
        "root_causes": [
            "Application is overwhelmed and not responding to health checks",
            "Health check endpoint is misconfigured",
            "Application stuck in deadlock or infinite loop",
            "Database connection issues causing health check timeout",
        ],
        "analyses": [
            "Liveness or readiness probe is failing, indicating the application is not responding correctly. This could be due to application hang, resource exhaustion, or misconfigured probes.",
            "Health check failures detected. The application may be experiencing high load or internal issues that prevent it from responding to health probes.",
        ],
        "strategy": "restart_pod",
        "reasoning": "Restarting the pod will terminate any stuck processes and allow the application to recover. If the issue is due to deadlock or hang, restart is the appropriate remediation.",
        "confidence": 0.82,
    },
    IssueType.PENDING_POD: {
        "root_causes": [
            "Insufficient resources available in the cluster",
            "Node selector or affinity rules cannot be satisfied",
            "PersistentVolumeClaim cannot be bound",
            "Taints on nodes preventing pod scheduling",
        ],
        "analyses": [
            "Pod remains in Pending state, indicating Kubernetes scheduler cannot find a suitable node. This is typically due to resource constraints or scheduling rules that cannot be satisfied.",
            "The pod cannot be scheduled. Analysis of scheduler events suggests resource constraints or affinity rules are preventing placement.",
        ],
        "strategy": "manual_intervention",
        "reasoning": "Pending pods typically require cluster-level intervention such as adding nodes or adjusting resource requests. Automated remediation is not appropriate for this scenario.",
        "confidence": 0.75,
    },
}


class MockAIProvider:
    """
    Mock AI provider that simulates LLM responses for demo purposes.
    No API keys or external services required!
    """
    
    def __init__(self):
        logger.info("mock_ai_provider_initialized", 
                   message="Using rule-based AI simulation (no API keys needed)")
    
    async def complete(self, prompt: str, issue: Issue) -> str:
        """
        Generate a simulated AI diagnosis based on issue type.
        
        Args:
            prompt: The diagnosis prompt (used for logging)
            issue: The issue to diagnose
            
        Returns:
            JSON string with diagnosis
        """
        # Simulate AI thinking time (makes demo feel more realistic)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Get template for this issue type
        template = DIAGNOSIS_TEMPLATES.get(
            issue.issue_type,
            DIAGNOSIS_TEMPLATES[IssueType.CRASH_LOOP_BACKOFF]  # Default
        )
        
        # Build response with some randomization for realism
        root_cause = random.choice(template["root_causes"])
        analysis = random.choice(template["analyses"])
        
        # Add context from the actual issue
        analysis += f"\n\nSpecific context: {issue.description}"
        
        if issue.logs:
            analysis += f"\n\nLog analysis: Found {len(issue.logs)} log entries. "
            # Look for error patterns in logs
            error_lines = [l for l in issue.logs if 'error' in l.lower() or 'exception' in l.lower()]
            if error_lines:
                analysis += f"Detected {len(error_lines)} error-related log entries."
        
        response = {
            "root_cause": root_cause,
            "analysis": analysis,
            "recommended_strategy": template["strategy"],
            "confidence": template["confidence"] + random.uniform(-0.05, 0.05),
            "reasoning": template["reasoning"],
            "alternative_strategies": self._get_alternatives(template["strategy"]),
            "requires_manual_intervention": template["strategy"] == "manual_intervention",
            "suggested_actions": self._get_suggested_actions(issue.issue_type),
        }
        
        logger.info(
            "mock_ai_diagnosis_generated",
            issue_type=issue.issue_type.value,
            strategy=response["recommended_strategy"],
            confidence=round(response["confidence"], 2),
        )
        
        return json.dumps(response)
    
    def _get_alternatives(self, primary: str) -> list:
        """Get alternative strategies."""
        alternatives = {
            "restart_pod": ["scale_up", "manual_intervention"],
            "scale_up": ["restart_pod", "increase_resources"],
            "rollback_deployment": ["restart_pod", "manual_intervention"],
            "increase_resources": ["restart_pod", "scale_up"],
            "manual_intervention": [],
        }
        return alternatives.get(primary, [])
    
    def _get_suggested_actions(self, issue_type: IssueType) -> list:
        """Get human-readable suggested actions."""
        actions = {
            IssueType.CRASH_LOOP_BACKOFF: [
                "Check application logs for startup errors",
                "Verify environment variables and config maps",
                "Review recent deployment changes",
            ],
            IssueType.OOM_KILLED: [
                "Profile application memory usage",
                "Review memory limits vs actual requirements",
                "Check for memory leak patterns",
            ],
            IssueType.IMAGE_PULL_BACKOFF: [
                "Verify image name and tag exist",
                "Check registry credentials",
                "Confirm network access to registry",
            ],
            IssueType.MEMORY_LEAK: [
                "Enable memory profiling",
                "Review object lifecycle management",
                "Check connection pool configurations",
            ],
            IssueType.HEALTH_CHECK_FAILURE: [
                "Review health check endpoint implementation",
                "Check for application deadlocks",
                "Verify probe timing configuration",
            ],
            IssueType.PENDING_POD: [
                "Check cluster resource availability",
                "Review node affinity rules",
                "Verify PVC status if used",
            ],
        }
        return actions.get(issue_type, ["Review application logs"])
    
    async def cleanup(self):
        """Cleanup - nothing needed for mock provider."""
        logger.info("mock_ai_provider_cleanup_complete")
