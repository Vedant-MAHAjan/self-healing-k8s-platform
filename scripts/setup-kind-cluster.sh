#!/bin/bash
# Setup a local kind cluster for testing

set -e

CLUSTER_NAME=${CLUSTER_NAME:-self-healing-test}

echo "Creating kind cluster: $CLUSTER_NAME..."

cat <<EOF | kind create cluster --name $CLUSTER_NAME --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF

echo "Installing Prometheus Operator..."
kubectl create namespace monitoring || true
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --wait

echo "Waiting for Prometheus to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=prometheus -n monitoring --timeout=300s

echo "Cluster setup complete!"
echo ""
echo "Next steps:"
echo "1. Build and load the operator image: ./scripts/build-and-load.sh"
echo "2. Deploy the operator: kubectl apply -f deploy/k8s/ "
echo "3. Test with examples: kubectl apply -f examples/scenarios/"
