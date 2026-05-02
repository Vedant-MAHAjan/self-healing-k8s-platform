"""
Prometheus metrics for the operator.
"""

import structlog
from prometheus_client import Counter, Histogram, Gauge, start_http_server


logger = structlog.get_logger()


# Define metrics
alerts_received_counter = Counter(
    'self_healing_alerts_received_total',
    'Total number of alerts received',
    ['issue_type', 'namespace'],
)

fixes_applied_counter = Counter(
    'self_healing_fixes_applied_total',
    'Total number of fixes successfully applied',
    ['strategy', 'namespace'],
)

fixes_failed_counter = Counter(
    'self_healing_fixes_failed_total',
    'Total number of failed fix attempts',
    ['strategy', 'namespace'],
)

ai_diagnosis_duration = Histogram(
    'self_healing_ai_diagnosis_duration_seconds',
    'Time spent on AI diagnosis',
    ['issue_type'],
)

active_issues_gauge = Gauge(
    'self_healing_active_issues',
    'Number of currently active issues',
    ['namespace'],
)

remediation_attempts_counter = Counter(
    'self_healing_remediation_attempts_total',
    'Total remediation attempts',
    ['strategy', 'status'],
)

control_decisions_counter = Counter(
    'self_healing_control_decisions_total',
    'Total control decisions made by the autonomous policy layer',
    ['action', 'strategy', 'namespace'],
)

scheduled_jobs_counter = Counter(
    'self_healing_scheduled_jobs_total',
    'Total remediation jobs scheduled by the control plane',
    ['workflow', 'status'],
)

workflow_steps_counter = Counter(
    'self_healing_workflow_steps_total',
    'Total workflow steps executed',
    ['workflow', 'step', 'status'],
)

circuit_breaker_state_gauge = Gauge(
    'self_healing_circuit_breaker_state',
    'Circuit breaker state encoded as 0=closed, 1=half-open, 2=open',
    ['breaker_key'],
)

service_issue_frequency_gauge = Gauge(
    'self_healing_service_issue_frequency_5m',
    'Recent issue frequency for a service over a 5 minute window',
    ['namespace', 'resource_name', 'issue_type'],
)

job_queue_depth_gauge = Gauge(
    'self_healing_job_queue_depth',
    'Number of queued remediation jobs waiting to execute',
)


def setup_metrics(port: int = 8000):
    """
    Start Prometheus metrics HTTP server.
    
    Args:
        port: Port to expose metrics on
    """
    try:
        start_http_server(port)
        logger.info("metrics_server_started", port=port)
    except Exception as e:
        logger.error(
            "failed_to_start_metrics_server",
            port=port,
            error=str(e),
        )
