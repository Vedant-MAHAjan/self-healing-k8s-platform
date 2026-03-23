"""
Self-Healing Kubernetes Operator

Main entry point for the operator using kopf framework.
Monitors Kubernetes resources and responds to events and Prometheus alerts.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import kopf
import structlog
from kubernetes import client, config

from healing_operator.config import Settings
from healing_operator.handlers import pod_handlers, deployment_handlers, alert_handlers
from healing_operator.diagnosis.ai_engine import AIEngine
from healing_operator.remediation.strategy_manager import StrategyManager
from healing_operator.utils.metrics import setup_metrics


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def setup_kubernetes_client():
    """Initialize Kubernetes client configuration."""
    try:
        # Try in-cluster config first
        config.load_incluster_config()
        logger.info("loaded_kubernetes_config", source="in-cluster")
    except config.ConfigException:
        # Fall back to kubeconfig
        config.load_kube_config()
        logger.info("loaded_kubernetes_config", source="kubeconfig")


@kopf.on.startup()
async def on_startup(settings: kopf.OperatorSettings, memo: kopf.Memo, **kwargs):
    """
    Called when the operator starts.
    Initialize connections, settings, and dependencies.
    """
    logger.info("operator_starting", version="0.1.0")
    
    # Load configuration
    app_settings = Settings()
    
    # Setup Kubernetes client
    setup_kubernetes_client()
    
    # Configure kopf settings
    settings.persistence.finalizer = "self-healing.k8s.io/finalizer"
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage()
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage()
    
    # Set watching parameters
    settings.watching.connect_timeout = 1 * 60
    settings.watching.server_timeout = 5 * 60
    
    # Configure posting
    settings.posting.level = logging.INFO
    
    # Initialize AI Engine
    ai_engine = AIEngine(settings=app_settings)
    await ai_engine.initialize()
    
    # Initialize Strategy Manager
    strategy_manager = StrategyManager(settings=app_settings)
    
    # Store in operator context for handlers to access via memo
    # Note: memo is shared across all handlers in kopf
    memo['settings'] = app_settings
    memo['ai_engine'] = ai_engine
    memo['strategy_manager'] = strategy_manager
    
    # Setup Prometheus metrics
    setup_metrics(app_settings.metrics_port)
    
    logger.info(
        "operator_started",
        dry_run=app_settings.dry_run,
        ai_provider=app_settings.ai_provider,
        auto_approve=app_settings.auto_approve_fixes,
    )


@kopf.on.cleanup()
async def on_cleanup(**kwargs):
    """Called when the operator is shutting down."""
    logger.info("operator_shutting_down")
    
    # Cleanup AI Engine
    memo = kwargs.get('memo', {})
    ai_engine = memo.get('ai_engine')
    if ai_engine:
        await ai_engine.cleanup()
    
    logger.info("operator_shutdown_complete")


def main():
    """Main entry point for the operator."""
    # Set log level from environment
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level))
    
    logger.info(
        "self_healing_operator_main",
        python_version=sys.version.split()[0],
    )
    
    # Run the operator
    kopf.run(
        clusterwide=True,
        liveness_endpoint="http://0.0.0.0:8080/healthz",
        priority=100,
    )


if __name__ == "__main__":
    main()
