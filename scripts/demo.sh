#!/bin/bash
# =============================================================================
# Self-Healing Kubernetes Demo
# =============================================================================
# This script runs the complete demo:
# 1. Creates a KIND cluster
# 2. Deploys the self-healing operator
# 3. Deploys a failing application
# 4. Watches the operator detect and fix the issue
#
# Requirements:
# - Docker
# - kind (will be installed if missing)
# - kubectl (will be installed if missing)
#
# Optional (for real AI):
# - Ollama with llama3 model
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
CLUSTER_NAME="self-healing-demo"
NAMESPACE="self-healing-system"
DEMO_NAMESPACE="demo"

print_banner() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}🚀 Self-Healing Kubernetes Platform Demo${NC}                      ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}     AI-powered automatic issue detection & remediation        ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}▶ $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_info() {
    echo -e "${YELLOW}  ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}  ✅ $1${NC}"
}

print_error() {
    echo -e "${RED}  ❌ $1${NC}"
}

check_dependencies() {
    print_step "Checking dependencies..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please install Docker first."
        exit 1
    fi
    print_success "Docker found"
    
    # Check/Install kind
    if ! command -v kind &> /dev/null; then
        print_info "Installing kind..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install kind || curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-darwin-amd64 && chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
        else
            curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
            chmod +x ./kind
            sudo mv ./kind /usr/local/bin/kind
        fi
    fi
    print_success "kind found"
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        print_info "Installing kubectl..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install kubectl
        else
            curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
            chmod +x kubectl
            sudo mv kubectl /usr/local/bin/
        fi
    fi
    print_success "kubectl found"
    
    # Check Ollama (optional)
    if command -v ollama &> /dev/null; then
        print_success "Ollama found - will use REAL AI!"
        USE_OLLAMA=true
        
        # Check if llama3 model is available
        if ollama list 2>/dev/null | grep -q "llama3"; then
            print_success "llama3 model available"
        else
            print_info "Pulling llama3 model (this may take a few minutes)..."
            ollama pull llama3 || print_info "Could not pull model, will use mock AI"
        fi
    else
        print_info "Ollama not found - will use smart rule-based AI"
        print_info "For real AI, install Ollama: https://ollama.ai"
        USE_OLLAMA=false
    fi
}

create_cluster() {
    print_step "Creating KIND cluster..."
    
    # Delete existing cluster if it exists
    if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
        print_info "Deleting existing cluster..."
        kind delete cluster --name $CLUSTER_NAME
    fi
    
    # Create new cluster
    cat <<EOF | kind create cluster --name $CLUSTER_NAME --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
EOF
    
    print_success "KIND cluster created"
    
    # Wait for cluster to be ready
    print_info "Waiting for cluster to be ready..."
    kubectl wait --for=condition=Ready nodes --all --timeout=60s
    print_success "Cluster is ready!"
}

build_and_load_operator() {
    print_step "Building operator image..."
    
    # Build Docker image
    docker build -t self-healing-operator:demo .
    
    print_success "Image built"
    
    # Load into KIND
    print_info "Loading image into KIND cluster..."
    kind load docker-image self-healing-operator:demo --name $CLUSTER_NAME
    
    print_success "Image loaded into cluster"
}

deploy_operator() {
    print_step "Deploying self-healing operator..."
    
    # Create namespace
    kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    
    # Determine AI provider
    if [ "$USE_OLLAMA" = true ]; then
        AI_PROVIDER="ollama"
        print_info "Using Ollama (real AI)"
    else
        AI_PROVIDER="mock"
        print_info "Using mock AI (smart rule-based)"
    fi
    
    # Apply ConfigMap with AI settings
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: self-healing-operator-config
  namespace: $NAMESPACE
data:
  OPERATOR_LOG_LEVEL: "INFO"
  OPERATOR_DRY_RUN: "false"
  OPERATOR_AI_PROVIDER: "$AI_PROVIDER"
  OPERATOR_OLLAMA_HOST: "http://host.docker.internal:11434"
  OPERATOR_OLLAMA_MODEL: "llama3"
  OPERATOR_AUTO_APPROVE_FIXES: "true"
  OPERATOR_REMEDIATION_COOLDOWN: "30"
EOF
    
    # Apply RBAC
    kubectl apply -f deploy/k8s/rbac.yaml
    
    # Apply deployment with demo image
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: self-healing-operator
  namespace: $NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: self-healing-operator
  template:
    metadata:
      labels:
        app: self-healing-operator
    spec:
      serviceAccountName: self-healing-operator
      containers:
      - name: operator
        image: self-healing-operator:demo
        imagePullPolicy: Never
        envFrom:
        - configMapRef:
            name: self-healing-operator-config
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
EOF
    
    # Wait for operator to be ready
    print_info "Waiting for operator to start..."
    kubectl wait --for=condition=ready pod -l app=self-healing-operator -n $NAMESPACE --timeout=120s
    
    print_success "Operator deployed and running!"
}

deploy_failing_app() {
    print_step "Deploying a failing application (CrashLoopBackOff)..."
    
    # Deploy app that will crash
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: buggy-app
  namespace: $DEMO_NAMESPACE
  labels:
    app: buggy-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: buggy-app
  template:
    metadata:
      labels:
        app: buggy-app
    spec:
      containers:
      - name: app
        image: busybox:latest
        command: ["sh", "-c"]
        args:
          - |
            echo "🐛 Application starting..."
            echo "💥 Simulating crash due to configuration error!"
            echo "ERROR: Missing required environment variable DATABASE_URL"
            exit 1
        resources:
          requests:
            cpu: 50m
            memory: 32Mi
          limits:
            cpu: 100m
            memory: 64Mi
EOF
    
    print_success "Failing app deployed"
    print_info "The app will crash and enter CrashLoopBackOff state..."
}

watch_healing() {
    print_step "Watching self-healing in action..."
    
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}What's happening:${NC}                                             ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                                ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  1. 🐛 Buggy app crashes (CrashLoopBackOff)                   ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  2. 👁️  Operator detects the issue                            ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  3. 🤖 AI analyzes logs and events                            ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  4. 💡 AI recommends remediation strategy                     ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  5. 🔧 Operator applies the fix automatically                 ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    # Show pod status
    print_info "Current pod status:"
    kubectl get pods -n $DEMO_NAMESPACE -w &
    WATCH_PID=$!
    
    # Wait a bit for crash
    sleep 10
    
    # Show operator logs
    echo ""
    print_info "Operator logs (watch for AI diagnosis):"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    kubectl logs -f -n $NAMESPACE deployment/self-healing-operator --tail=50 &
    LOGS_PID=$!
    
    # Let it run for a while
    sleep 30
    
    # Clean up background processes
    kill $WATCH_PID 2>/dev/null || true
    kill $LOGS_PID 2>/dev/null || true
    
    echo ""
    print_success "Demo sequence completed!"
}

show_summary() {
    print_step "Demo Summary"
    
    echo ""
    echo -e "${GREEN}The self-healing operator demonstrated:${NC}"
    echo ""
    echo "  ✅ Automatic detection of CrashLoopBackOff"
    echo "  ✅ AI-powered root cause analysis"
    echo "  ✅ Intelligent remediation strategy selection"
    echo "  ✅ Automatic fix application"
    echo ""
    echo -e "${CYAN}Commands to explore:${NC}"
    echo ""
    echo "  # View operator logs"
    echo "  kubectl logs -f -n $NAMESPACE deployment/self-healing-operator"
    echo ""
    echo "  # View pod status"
    echo "  kubectl get pods -n $DEMO_NAMESPACE"
    echo ""
    echo "  # Deploy another failing scenario"
    echo "  kubectl apply -f examples/scenarios/oom-killed.yaml"
    echo ""
    echo "  # Cleanup"
    echo "  make demo-clean"
    echo ""
}

cleanup() {
    print_step "Cleaning up..."
    kind delete cluster --name $CLUSTER_NAME 2>/dev/null || true
    print_success "Cleanup complete"
}

# Handle Ctrl+C
trap cleanup INT

# Main execution
main() {
    print_banner
    check_dependencies
    create_cluster
    build_and_load_operator
    deploy_operator
    
    # Create demo namespace (needed for test scenarios)
    print_info "Creating demo namespace..."
    kubectl create namespace $DEMO_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    print_success "Demo namespace created"
    
    # Only deploy app if not running in infra-only mode
    if [ "${INFRA_ONLY:-false}" != "true" ]; then
        deploy_failing_app
        watch_healing
        show_summary
    else
        echo ""
        echo -e "${GREEN}✅ Infrastructure ready!${NC}"
        echo ""
        echo -e "${CYAN}Next steps:${NC}"
        echo "  1. Deploy your test scenarios:"
        echo "     kubectl apply -f examples/scenarios/oom-killed.yaml"
        echo "     kubectl apply -f examples/scenarios/crash-loop.yaml"
        echo ""
        echo "  2. Watch operator logs:"
        echo "     kubectl logs -f -n self-healing-system deployment/self-healing-operator"
        echo ""
    fi
}

# Run with argument handling
case "${1:-}" in
    clean)
        cleanup
        ;;
    infra-only)
        export INFRA_ONLY=true
        main
        ;;
    *)
        main
        ;;
esac
