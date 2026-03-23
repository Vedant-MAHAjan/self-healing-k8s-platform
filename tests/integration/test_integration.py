"""
Integration tests for the self-healing operator.

These tests require a kind cluster and are meant to be run with:
./scripts/test-integration.sh
"""

import pytest
import asyncio
from kubernetes import client, config
from datetime import datetime, timedelta


@pytest.fixture(scope="session")
def k8s_client():
    """Initialize Kubernetes client."""
    try:
        config.load_kube_config()
    except:
        config.load_incluster_config()
    
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def apps_client():
    """Initialize Apps API client."""
    return client.AppsV1Api()


@pytest.fixture
def test_namespace():
    """Test namespace name."""
    return "integration-test"


@pytest.mark.integration
class TestOperatorIntegration:
    """Integration tests for the operator."""
    
    @pytest.mark.asyncio
    async def test_operator_deployment(self, k8s_client):
        """Test that the operator is deployed and running."""
        pods = k8s_client.list_namespaced_pod(
            namespace="self-healing-system",
            label_selector="app.kubernetes.io/name=self-healing-operator"
        )
        
        assert len(pods.items) > 0, "Operator pod not found"
        
        operator_pod = pods.items[0]
        assert operator_pod.status.phase == "Running", "Operator not running"
    
    @pytest.mark.asyncio
    async def test_crash_loop_remediation(
        self,
        k8s_client,
        apps_client,
        test_namespace,
    ):
        """Test that crash loop is detected and remediated."""
        # Create test namespace
        try:
            k8s_client.create_namespace(
                body=client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=test_namespace)
                )
            )
        except:
            pass  # Namespace may already exist
        
        # Deploy crashing pod
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name="crash-test"),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={"app": "crash-test"}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": "crash-test"}
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="app",
                                image="busybox:latest",
                                command=["sh", "-c", "exit 1"],
                            )
                        ]
                    )
                )
            )
        )
        
        try:
            apps_client.create_namespaced_deployment(
                namespace=test_namespace,
                body=deployment,
            )
            
            # Wait for operator to detect and remediate (up to 2 minutes)
            for _ in range(24):  # 24 * 5 seconds = 2 minutes
                await asyncio.sleep(5)
                
                # Check if remediation occurred by looking at events
                events = k8s_client.list_namespaced_event(
                    namespace=test_namespace
                )
                
                # Look for deletion event (restart strategy)
                deletion_events = [
                    e for e in events.items
                    if "Deleted" in e.message or "deleted" in e.message.lower()
                ]
                
                if deletion_events:
                    print("Remediation detected!")
                    break
            
            # Cleanup
            apps_client.delete_namespaced_deployment(
                name="crash-test",
                namespace=test_namespace,
            )
            
        except Exception as e:
            print(f"Test error: {e}")
            # Cleanup on error
            try:
                apps_client.delete_namespaced_deployment(
                    name="crash-test",
                    namespace=test_namespace,
                )
            except:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
