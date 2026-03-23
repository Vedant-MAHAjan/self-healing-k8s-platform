#!/bin/bash
# Deploy the operator with Helm

set -e

NAMESPACE=${NAMESPACE:-self-healing-system}
RELEASE_NAME=${RELEASE_NAME:-self-healing-operator}

echo "Creating namespace $NAMESPACE..."
kubectl create namespace $NAMESPACE || true

echo "Creating secrets..."
read -sp "Enter OpenAI API Key: " OPENAI_KEY
echo ""

kubectl create secret generic self-healing-operator-secrets \
  --from-literal=OPERATOR_OPENAI_API_KEY=$OPENAI_KEY \
  --namespace=$NAMESPACE \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Deploying operator with Helm..."
helm upgrade --install $RELEASE_NAME ./deploy/helm \
  --namespace $NAMESPACE \
  --set operator.dryRun=false \
  --set ai.provider=openai \
  --set remediation.autoApprove=false \
  --wait

echo ""
echo "Operator deployed successfully!"
echo ""
echo "Check status:"
echo "  kubectl get pods -n $NAMESPACE"
echo ""
echo "View logs:"
echo "  kubectl logs -f -n $NAMESPACE deployment/$RELEASE_NAME"
echo ""
echo "View metrics:"
echo "  kubectl port-forward -n $NAMESPACE svc/$RELEASE_NAME-metrics 8000:8000"
echo "  curl localhost:8000/metrics"
