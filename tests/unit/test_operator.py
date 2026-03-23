"""
Unit tests for the self-healing operator.
"""

import pytest
from datetime import datetime
from operator.models import (
    Issue,
    IssueType,
    PodInfo,
    RemediationStrategy,
)
from operator.config import Settings


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        dry_run=True,
        ai_provider="openai",
        openai_api_key="test-key",
        auto_approve_fixes=True,
    )


@pytest.fixture
def sample_pod_info():
    """Create sample pod info."""
    return PodInfo(
        name="test-pod",
        namespace="default",
        uid="12345",
        status="Running",
        restart_count=5,
        container_statuses=[
            {
                'name': 'app',
                'ready': False,
                'restartCount': 5,
                'state': {
                    'waiting': {
                        'reason': 'CrashLoopBackOff',
                        'message': 'Back-off restarting failed container',
                    }
                }
            }
        ],
        labels={'app': 'test-app'},
    )


@pytest.fixture
def sample_issue(sample_pod_info):
    """Create a sample issue."""
    return Issue(
        issue_id="test-issue-1",
        issue_type=IssueType.CRASH_LOOP_BACKOFF,
        resource_kind="Pod",
        resource_name="test-pod",
        resource_namespace="default",
        description="Pod is in CrashLoopBackOff",
        severity="high",
        detected_at=datetime.utcnow(),
        pod_info=sample_pod_info,
    )


class TestIssueDetection:
    """Test issue detection logic."""
    
    def test_crash_loop_detection(self, sample_issue):
        """Test crash loop detection."""
        assert sample_issue.issue_type == IssueType.CRASH_LOOP_BACKOFF
        assert sample_issue.severity == "high"
        assert sample_issue.pod_info.restart_count == 5
    
    def test_issue_id_generation(self, sample_issue):
        """Test issue ID is generated correctly."""
        assert "test-issue" in sample_issue.issue_id
        assert sample_issue.issue_id is not None


class TestRemediation:
    """Test remediation strategies."""
    
    @pytest.mark.asyncio
    async def test_restart_pod_strategy(self, sample_issue, settings):
        """Test pod restart strategy."""
        from operator.remediation.strategies import restart_pod_strategy
        from operator.models import Diagnosis
        from operator.utils.kubernetes_helper import KubernetesHelper
        
        diagnosis = Diagnosis(
            issue=sample_issue,
            root_cause="Container crashes on startup",
            analysis="The container is crashing immediately",
            recommended_strategy=RemediationStrategy.RESTART_POD,
            confidence=0.9,
            reasoning="Restarting the pod may help",
        )
        
        k8s_helper = KubernetesHelper()
        
        # In dry run mode, should return True
        result = await restart_pod_strategy(
            diagnosis=diagnosis,
            k8s_helper=k8s_helper,
            settings=settings,
            dry_run=True,
        )
        
        assert result is True


class TestConfig:
    """Test configuration management."""
    
    def test_default_settings(self):
        """Test default settings are loaded."""
        settings = Settings()
        assert settings.dry_run == False
        assert settings.log_level == "INFO"
        assert settings.metrics_port == 8000
    
    def test_custom_settings(self):
        """Test custom settings override defaults."""
        settings = Settings(
            dry_run=True,
            log_level="DEBUG",
            metrics_port=9000,
        )
        assert settings.dry_run == True
        assert settings.log_level == "DEBUG"
        assert settings.metrics_port == 9000


class TestModels:
    """Test data models."""
    
    def test_pod_info_creation(self, sample_pod_info):
        """Test PodInfo model."""
        assert sample_pod_info.name == "test-pod"
        assert sample_pod_info.namespace == "default"
        assert sample_pod_info.restart_count == 5
    
    def test_issue_creation(self, sample_issue):
        """Test Issue model."""
        assert sample_issue.resource_kind == "Pod"
        assert sample_issue.resource_name == "test-pod"
        assert sample_issue.issue_type == IssueType.CRASH_LOOP_BACKOFF


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
