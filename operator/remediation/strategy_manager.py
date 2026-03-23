"""
Remediation strategy manager.
Executes remediation strategies based on AI diagnosis.
"""

import structlog
from datetime import datetime
from typing import Dict, Callable

from healing_operator.config import Settings
from healing_operator.models import (
    Diagnosis,
    RemediationAction,
    RemediationStrategy,
    RemediationStatus,
)
from healing_operator.remediation.strategies import (
    restart_pod_strategy,
    scale_up_strategy,
    scale_down_strategy,
    rollback_deployment_strategy,
    increase_resources_strategy,
    evict_pod_strategy,
)
from healing_operator.utils.kubernetes_helper import KubernetesHelper


logger = structlog.get_logger()


class StrategyManager:
    """
    Manages and executes remediation strategies.
    Routes to the appropriate strategy based on diagnosis.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.k8s_helper = KubernetesHelper()
        
        # Map strategies to their implementation functions
        self.strategy_handlers: Dict[RemediationStrategy, Callable] = {
            RemediationStrategy.RESTART_POD: restart_pod_strategy,
            RemediationStrategy.SCALE_UP: scale_up_strategy,
            RemediationStrategy.SCALE_DOWN: scale_down_strategy,
            RemediationStrategy.ROLLBACK_DEPLOYMENT: rollback_deployment_strategy,
            RemediationStrategy.INCREASE_RESOURCES: increase_resources_strategy,
            RemediationStrategy.EVICT_POD: evict_pod_strategy,
        }
        
        logger.info("strategy_manager_initialized")
    
    async def execute(self, diagnosis: Diagnosis, dry_run: bool = False) -> bool:
        """
        Execute a remediation strategy based on diagnosis.
        
        Args:
            diagnosis: The AI diagnosis with recommended strategy
            dry_run: If True, only log actions without executing
            
        Returns:
            True if remediation was successful, False otherwise
        """
        strategy = diagnosis.recommended_strategy
        
        # Check if strategy is enabled in settings
        if not self._is_strategy_enabled(strategy):
            logger.warning(
                "strategy_disabled",
                strategy=strategy.value,
                issue_id=diagnosis.issue.issue_id,
            )
            return False
        
        # Create remediation action record
        action = RemediationAction(
            action_id=f"{diagnosis.issue.issue_id}-{strategy.value}",
            diagnosis=diagnosis,
            strategy=strategy,
            status=RemediationStatus.PENDING,
            initiated_at=datetime.utcnow(),
            dry_run=dry_run,
        )
        
        logger.info(
            "executing_remediation",
            action_id=action.action_id,
            strategy=strategy.value,
            dry_run=dry_run,
        )
        
        # Execute the strategy
        try:
            action.status = RemediationStatus.IN_PROGRESS
            
            # Get the strategy handler
            handler = self.strategy_handlers.get(strategy)
            
            if not handler:
                logger.error(
                    "no_handler_for_strategy",
                    strategy=strategy.value,
                )
                action.status = RemediationStatus.FAILED
                action.error = f"No handler implemented for {strategy.value}"
                return False
            
            # Execute the strategy
            success = await handler(
                diagnosis=diagnosis,
                k8s_helper=self.k8s_helper,
                settings=self.settings,
                dry_run=dry_run,
            )
            
            if success:
                action.status = RemediationStatus.COMPLETED
                action.completed_at = datetime.utcnow()
                action.result = "Remediation completed successfully"
                
                logger.info(
                    "remediation_successful",
                    action_id=action.action_id,
                    strategy=strategy.value,
                )
                return True
            else:
                action.status = RemediationStatus.FAILED
                action.error = "Strategy execution returned False"
                
                logger.error(
                    "remediation_failed",
                    action_id=action.action_id,
                    strategy=strategy.value,
                )
                return False
        
        except Exception as e:
            action.status = RemediationStatus.FAILED
            action.error = str(e)
            action.completed_at = datetime.utcnow()
            
            logger.error(
                "remediation_exception",
                action_id=action.action_id,
                strategy=strategy.value,
                error=str(e),
                exc_info=True,
            )
            return False
    
    def _is_strategy_enabled(self, strategy: RemediationStrategy) -> bool:
        """Check if a strategy is enabled in settings."""
        strategy_settings = {
            RemediationStrategy.RESTART_POD: self.settings.enable_pod_restart,
            RemediationStrategy.SCALE_UP: self.settings.enable_scaling,
            RemediationStrategy.SCALE_DOWN: self.settings.enable_scaling,
            RemediationStrategy.ROLLBACK_DEPLOYMENT: self.settings.enable_rollback,
            RemediationStrategy.INCREASE_RESOURCES: True,  # Always enabled
            RemediationStrategy.EVICT_POD: True,  # Always enabled
        }
        
        return strategy_settings.get(strategy, True)
