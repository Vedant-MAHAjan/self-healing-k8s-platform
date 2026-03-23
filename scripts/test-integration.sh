#!/bin/bash
# Run integration tests

set -e

echo "Setting up test environment..."

# Create kind cluster if it doesn't exist
if ! kind get clusters | grep -q "self-healing-test"; then
    echo "Creating test cluster..."
    ./scripts/setup-kind-cluster.sh
fi

echo "Building and loading operator image..."
./scripts/build-and-load.sh

echo "Deploying operator..."
kubectl apply -f deploy/k8s/

echo "Waiting for operator to be ready..."
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=self-healing-operator \
  -n self-healing-system \
  --timeout=300s

echo "Running integration tests..."
pytest tests/integration/ -v -m integration

echo "Integration tests complete!"
