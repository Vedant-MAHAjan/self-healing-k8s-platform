#!/bin/bash
# =============================================================================
# Self-Healing Kubernetes Platform — Demo Script
# =============================================================================
# Usage:
#   ./scripts/demo.sh                     Full demo (cluster + operator + crash)
#   ./scripts/demo.sh infra-only          Cluster + operator, no scenario
#   ./scripts/demo.sh autonomous          Show full autonomous control pipeline
#   ./scripts/demo.sh scenario <name>     Deploy one scenario by name
#   ./scripts/demo.sh watch               Tail filtered autonomous control logs
#   ./scripts/demo.sh state               Show pods, operator logs, incident count
#   ./scripts/demo.sh clean               Delete demo cluster
#
# No API keys required.  AI provider priority:
#   1. Ollama (local LLM, free) — detected automatically if running
#   2. Mock provider (built-in rule-based) — zero setup, always works
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

CLUSTER_NAME="self-healing-demo"
NAMESPACE="self-healing-system"
DEMO_NAMESPACE="demo"

# ─── Utilities ────────────────────────────────────────────────────────────────

print_banner() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}🚀 Self-Healing Kubernetes Platform${NC}                          ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}     AI-powered autonomous detection & remediation              ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}     Zero cost · No API keys · 100% local                      ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}▶ $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_info()    { echo -e "${YELLOW}  ℹ  $1${NC}"; }
print_success() { echo -e "${GREEN}  ✅ $1${NC}"; }
print_error()   { echo -e "${RED}  ❌ $1${NC}"; }
print_event()   { echo -e "${MAGENTA}  ⚡ $1${NC}"; }

# ─── Dependency check ─────────────────────────────────────────────────────────

check_dependencies() {
    print_step "Checking dependencies"

    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please install Docker first."
        exit 1
    fi
    print_success "Docker found"

    if ! command -v kind &> /dev/null; then
        print_info "Installing kind..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install kind 2>/dev/null || \
              curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-darwin-arm64 && \
              chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
        else
            curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
            chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
        fi
    fi
    print_success "kind found"

    if ! command -v kubectl &> /dev/null; then
        print_info "Installing kubectl..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install kubectl
        else
            curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
            chmod +x kubectl && sudo mv kubectl /usr/local/bin/
        fi
    fi
    print_success "kubectl found"

    USE_OLLAMA=false
    if command -v ollama &> /dev/null && ollama list 2>/dev/null | grep -q "llama3"; then
        print_success "Ollama + llama3 detected — will use real local LLM"
        USE_OLLAMA=true
    else
        print_info "Ollama/llama3 not found — using built-in mock AI (no setup needed)"
        print_info "For real AI: brew install ollama && ollama pull llama3 && ollama serve"
    fi
    export USE_OLLAMA
}

# ─── Cluster ──────────────────────────────────────────────────────────────────

create_cluster() {
    print_step "Creating KIND cluster"

    if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
        print_info "Deleting existing cluster..."
        kind delete cluster --name "$CLUSTER_NAME"
    fi

    cat <<EOF | kind create cluster --name "$CLUSTER_NAME" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
EOF

    kubectl wait --for=condition=Ready nodes --all --timeout=60s
    print_success "Cluster ready"
}

# ─── Operator ─────────────────────────────────────────────────────────────────

build_and_load_operator() {
    print_step "Building operator image"
    docker build -t self-healing-operator:demo . --quiet
    kind load docker-image self-healing-operator:demo --name "$CLUSTER_NAME"
    print_success "Image built and loaded"
}

deploy_operator() {
    print_step "Deploying self-healing operator"

    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

    if [ "$USE_OLLAMA" = true ]; then
        AI_PROVIDER="ollama"
        print_info "AI provider: Ollama (real local LLM)"
    else
        AI_PROVIDER="mock"
        print_info "AI provider: Mock (built-in rule-based, zero cost)"
    fi

    # ConfigMap — all env vars for the operator
    kubectl apply -f - <<EOF
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
  OPERATOR_ENABLE_AUTONOMOUS_CONTROL: "true"
  OPERATOR_SCHEDULER_POLL_INTERVAL: "3"
  OPERATOR_SCHEDULER_WORKER_CONCURRENCY: "2"
  OPERATOR_METRICS_WINDOW_MINUTES: "15"
  OPERATOR_STATE_STORE_PATH: "/tmp/self-healing-control.db"
EOF

    kubectl apply -f deploy/k8s/rbac.yaml

    kubectl apply -f - <<EOF
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

    print_info "Waiting for operator to start..."
    kubectl wait --for=condition=ready pod -l app=self-healing-operator \
        -n "$NAMESPACE" --timeout=120s
    print_success "Operator running"
}

ensure_demo_namespace() {
    kubectl create namespace "$DEMO_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
}

# ─── Scenario deployment ──────────────────────────────────────────────────────

deploy_scenario() {
    local name="${1:-crash-loop}"
    local file="examples/scenarios/${name}.yaml"

    if [ ! -f "$file" ]; then
        print_error "Scenario file not found: $file"
        echo ""
        echo "  Available scenarios:"
        ls examples/scenarios/*.yaml 2>/dev/null | xargs -n1 basename | sed 's/.yaml//' | sed 's/^/    /'
        exit 1
    fi

    ensure_demo_namespace
    print_step "Deploying scenario: $name"
    kubectl apply -f "$file"
    print_success "Scenario deployed: $name"
    print_info "Watch the operator detect and remediate this issue with:"
    echo "        make demo-watch"
}

deploy_crash_app() {
    print_step "Deploying failing application (CrashLoopBackOff)"
    ensure_demo_namespace

    kubectl apply -f - <<EOF
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
            echo "Application starting..."
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
    print_success "Failing app deployed — entering CrashLoopBackOff"
}

# ─── Autonomous control plane demo ───────────────────────────────────────────

demo_autonomous() {
    print_banner

    # Verify the cluster + operator are up
    if ! kubectl get deployment self-healing-operator -n "$NAMESPACE" &>/dev/null; then
        print_error "Operator not running. Run 'make demo-infra' first."
        exit 1
    fi

    print_step "Autonomous Control Plane Demo"
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  What you will see:                                              ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                                  ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Phase 1 — OOM scenario                                          ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    Detection → AI Diagnosis → Decision Engine                    ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    → Job Scheduler queues 'increase_resources'                   ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    → Execution → State store updated                             ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                                  ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Phase 2 — Crash loop (repeated failures)                        ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    Retry engine → exponential backoff                            ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    → Circuit breaker opens after threshold                       ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    → Decision engine escalates (stops blind retries)             ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                                  ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Phase 3 — Watch multi-step workflow                             ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    restart_pod → scale_up → rollback (state machine)             ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Phase 1: OOM
    print_event "Phase 1: Deploying OOM scenario..."
    ensure_demo_namespace
    if [ -f "examples/scenarios/oom-killed.yaml" ]; then
        kubectl apply -f examples/scenarios/oom-killed.yaml
    else
        # Inline OOM scenario if file missing
        kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memory-hog
  namespace: demo
  labels:
    app: memory-hog
spec:
  replicas: 1
  selector:
    matchLabels:
      app: memory-hog
  template:
    metadata:
      labels:
        app: memory-hog
    spec:
      containers:
      - name: memory-hog
        image: polinux/stress:latest
        command: ["stress"]
        args: ["--vm", "1", "--vm-bytes", "200M", "--vm-keep"]
        resources:
          requests:
            cpu: 50m
            memory: 50Mi
          limits:
            cpu: 200m
            memory: 64Mi
EOF
    fi
    print_success "OOM scenario running — watch for 'OOMKilled' then auto-remediation"
    sleep 2

    # Phase 2: Crash loop
    print_event "Phase 2: Deploying crash-loop scenario..."
    deploy_crash_app
    print_success "Crash loop running — watch for retry + backoff decisions"
    sleep 2

    # Phase 3: Filtered log stream
    print_event "Phase 3: Streaming autonomous control plane logs (30 seconds)..."
    echo ""
    echo -e "${YELLOW}Key log events to watch:${NC}"
    echo "  autonomous_issue_processing_started  → issue picked up"
    echo "  control_decision_made               → policy decision (action + strategy)"
    echo "  metrics_snapshot_built              → trend data (5m/15m frequency)"
    echo "  workflow_plan_built                 → multi-step plan selected"
    echo "  job_scheduled                       → persisted in SQLite queue"
    echo "  job_execution_started               → worker running strategy"
    echo "  job_completed / job_retried         → success or backoff"
    echo "  retry_delay_computed                → exponential delay value"
    echo "  circuit_breaker_opened              → breaker tripped"
    echo "  circuit_breaker_open                → blocking execution"
    echo ""

    OPERATOR_POD=$(kubectl get pod -n "$NAMESPACE" -l app=self-healing-operator \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [ -n "$OPERATOR_POD" ]; then
        kubectl logs -f -n "$NAMESPACE" "$OPERATOR_POD" --tail=20 2>/dev/null | \
            grep --line-buffered -E \
                '"autonomous_|control_decision|metrics_snapshot|workflow_plan|job_schedul|job_execut|job_complet|job_retri|job_fail|retry_delay|circuit_breaker|remediation_successful|fixes_applied"' &
        LOG_PID=$!
        sleep 30
        kill "$LOG_PID" 2>/dev/null || true
    else
        print_info "Operator pod not found — check 'make demo-infra' completed"
    fi

    echo ""
    print_success "Autonomous demo complete!"
    _print_next_steps
}

# ─── Watch ────────────────────────────────────────────────────────────────────

watch_logs() {
    OPERATOR_POD=$(kubectl get pod -n "$NAMESPACE" -l app=self-healing-operator \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [ -z "$OPERATOR_POD" ]; then
        print_error "Operator pod not found. Run 'make demo-infra' first."
        exit 1
    fi

    echo ""
    echo -e "${CYAN}Streaming autonomous control plane events (Ctrl-C to stop)...${NC}"
    echo -e "${YELLOW}Filters: decisions · scheduling · circuit breaker · retry · workflow${NC}"
    echo ""

    kubectl logs -f -n "$NAMESPACE" "$OPERATOR_POD" --tail=20 2>/dev/null | \
        grep --line-buffered -E \
            '"autonomous_|control_decision|metrics_snapshot|workflow_plan|job_schedul|job_execut|job_complet|job_retri|job_fail|retry_delay|circuit_breaker|pod_issue_detected|alert_handler|remediation_successful|fixes_applied|ai_diagnosis"'
}

# ─── State ────────────────────────────────────────────────────────────────────

show_state() {
    print_step "System State"

    echo ""
    echo -e "${GREEN}Operator pod:${NC}"
    kubectl get pod -n "$NAMESPACE" -l app=self-healing-operator 2>/dev/null || \
        print_info "Operator not running. Run 'make demo-infra'."

    echo ""
    echo -e "${GREEN}Demo workloads:${NC}"
    kubectl get pods -n "$DEMO_NAMESPACE" 2>/dev/null || \
        print_info "No workloads in demo namespace"

    echo ""
    echo -e "${GREEN}Recent operator log events (last 30 lines, filtered):${NC}"
    OPERATOR_POD=$(kubectl get pod -n "$NAMESPACE" -l app=self-healing-operator \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$OPERATOR_POD" ]; then
        kubectl logs -n "$NAMESPACE" "$OPERATOR_POD" --tail=80 2>/dev/null | \
            grep -E '"autonomous_|control_decision|job_|circuit_breaker|pod_issue|fixes_' | \
            tail -30 || print_info "No matching events yet"
    fi

    echo ""
    echo -e "${GREEN}SQLite incident count:${NC}"
    if [ -n "$OPERATOR_POD" ]; then
        kubectl exec -n "$NAMESPACE" "$OPERATOR_POD" -- \
            sqlite3 /tmp/self-healing-control.db \
            "SELECT status, COUNT(*) FROM incidents GROUP BY status;" 2>/dev/null || \
            print_info "State store empty or not accessible"

        echo ""
        echo -e "${GREEN}Job queue (last 5):${NC}"
        kubectl exec -n "$NAMESPACE" "$OPERATOR_POD" -- \
            sqlite3 /tmp/self-healing-control.db \
            "SELECT job_id, strategy, status, attempts, updated_at FROM jobs ORDER BY updated_at DESC LIMIT 5;" \
            2>/dev/null || print_info "No jobs yet"

        echo ""
        echo -e "${GREEN}Circuit breaker states:${NC}"
        kubectl exec -n "$NAMESPACE" "$OPERATOR_POD" -- \
            sqlite3 /tmp/self-healing-control.db \
            "SELECT breaker_key, state, failure_count FROM breaker_states;" \
            2>/dev/null || print_info "No breaker state recorded yet"
    fi
}

# ─── Watch healing ────────────────────────────────────────────────────────────

watch_healing() {
    print_step "Watching self-healing in action"

    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  Autonomous pipeline:                                         ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Detect → AI Diagnose → Decide → Schedule → Execute → Store  ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    kubectl get pods -n "$DEMO_NAMESPACE" -w &
    WATCH_PID=$!

    sleep 10

    OPERATOR_POD=$(kubectl get pod -n "$NAMESPACE" -l app=self-healing-operator \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$OPERATOR_POD" ]; then
        kubectl logs -f -n "$NAMESPACE" "$OPERATOR_POD" --tail=30 &
        LOGS_PID=$!
    fi

    sleep 30

    kill "$WATCH_PID" 2>/dev/null || true
    kill "$LOGS_PID" 2>/dev/null || true

    print_success "Demo sequence complete!"
}

_print_next_steps() {
    echo ""
    echo -e "${CYAN}Next steps:${NC}"
    echo ""
    echo "  make demo-watch                           # Live filtered log stream"
    echo "  make demo-state                           # Pod + incident + job status"
    echo "  make demo-scenario SCENARIO=oom-killed    # Deploy another scenario"
    echo "  make demo-clean                           # Tear down cluster"
    echo ""
}

show_summary() {
    print_step "Demo Summary"
    echo ""
    echo -e "${GREEN}What the operator demonstrated:${NC}"
    echo ""
    echo "  ✅ Real-time detection of CrashLoopBackOff"
    echo "  ✅ AI root cause analysis (Ollama or built-in mock)"
    echo "  ✅ Policy-driven decision (Decision Engine)"
    echo "  ✅ Persistent job scheduling (SQLite-backed queue)"
    echo "  ✅ Exponential backoff retries (Retry Engine)"
    echo "  ✅ Per-service circuit breaking"
    echo "  ✅ Multi-step workflow orchestration"
    echo "  ✅ Incident + state history (State Store)"
    echo ""
    _print_next_steps
}

cleanup() {
    print_step "Cleaning up"
    kind delete cluster --name "$CLUSTER_NAME" 2>/dev/null || true
    print_success "Cleanup complete"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    print_banner
    check_dependencies
    create_cluster
    build_and_load_operator
    deploy_operator
    ensure_demo_namespace

    if [ "${INFRA_ONLY:-false}" != "true" ]; then
        deploy_crash_app
        watch_healing
        show_summary
    else
        print_success "Infrastructure ready!"
        echo ""
        echo -e "${CYAN}Available next steps:${NC}"
        echo "  make demo-scenario SCENARIO=oom-killed    # Deploy OOM scenario"
        echo "  make demo-scenario SCENARIO=crash-loop    # Deploy crash scenario"
        echo "  make demo-autonomous                      # Full autonomous pipeline demo"
        echo "  make demo-watch                           # Live log stream"
        echo "  make demo-state                           # Current system state"
        echo ""
    fi
}

trap cleanup INT

case "${1:-}" in
    clean)
        cleanup
        ;;
    infra-only)
        export INFRA_ONLY=true
        main
        ;;
    autonomous)
        demo_autonomous
        ;;
    scenario)
        deploy_scenario "${2:-crash-loop}"
        ;;
    watch)
        watch_logs
        ;;
    state)
        show_state
        ;;
    *)
        main
        ;;
esac
