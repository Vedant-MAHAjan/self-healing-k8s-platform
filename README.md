# Self-Healing Kubernetes Platform

A local-first, AI-assisted Kubernetes operator that detects failures, diagnoses root causes, and remediates issues through a policy-driven autonomous control plane. The project is designed to run without external API keys or cloud services. If Ollama is available, it uses a local LLM; otherwise it falls back to the built-in mock provider.

This README reflects the current repository state. It covers the core control-plane concepts, the demo path, and a complete source map of the tracked project files. Generated artifacts, caches, and the local virtual environment are intentionally omitted from the source map.

## Local-First Runtime

| Component | Default |
|---|---|
| AI diagnosis | Ollama if available, otherwise built-in mock provider |
| State storage | SQLite on disk |
| Kubernetes target | Local KIND cluster |
| Metrics | Self-hosted Prometheus client metrics |

## System Architecture

The operator now runs as an autonomous control system rather than a simple event-to-remediation loop.

```text
Metrics Aggregator
   ->
Detection Layer (Kopf handlers)
   ->
AI Diagnosis Engine
   ->
Decision Engine
   ->
Circuit Breaker
   ->
Retry + Backoff Engine
   ->
Job Scheduler
   ->
Execution Layer (remediation strategies)
   ->
Feedback + State Store
```

The important shift is that diagnosis no longer maps directly to action. The decision engine, breaker, retry engine, scheduler, and state store now sit between detection and execution so the system can make policy-driven, stateful decisions.

## Core Control Plane Concepts

### Decision Engine

The decision engine is the policy layer between diagnosis and execution. It evaluates the detected issue, the AI diagnosis confidence, the recent failure history, and the metrics trend before choosing an action. It can decide to remediate immediately, delay and retry, escalate, ignore, or request manual review.

This layer is deterministic. It uses policy data from the config manager and does not depend on the AI provider at decision time. That means a failed or low-confidence diagnosis still has a safe fallback path.

Key files:
- `k8s_operator/decision_engine/engine.py` implements the decision model and evaluation logic.
- `k8s_operator/decision_engine/__init__.py` exports the public API.
- `k8s_operator/control_plane.py` wires decisions into the orchestration flow.

### Circuit Breaker

The circuit breaker isolates repeated remediation failures per service. It tracks per-resource state and transitions through `CLOSED`, `OPEN`, and `HALF_OPEN` states. When the failure threshold is exceeded, the breaker opens and blocks repeated remediation until the cooldown expires. In half-open mode it allows a probe to test recovery.

This prevents the operator from repeatedly hammering a broken deployment or creating cascading failures across the system.

Key files:
- `k8s_operator/circuit_breaker/breaker.py` implements the state machine and persistence.
- `k8s_operator/circuit_breaker/__init__.py` exports breaker types.
- `k8s_operator/state_store/store.py` persists breaker state in SQLite.

### Retry + Backoff

The retry engine decides whether a failure is transient or permanent and computes the next retry delay. It uses exponential backoff with jitter and enforces maximum retry limits. Permanent failures such as invalid configuration, permission errors, or manual-intervention cases are not retried blindly.

This keeps the system resilient without becoming aggressive or noisy.

Key files:
- `k8s_operator/retry_engine/engine.py` classifies failures and computes delays.
- `k8s_operator/retry_engine/__init__.py` exports the retry API.
- `k8s_operator/control_plane.py` uses retry decisions to reschedule or escalate.

### Job Scheduler

The job scheduler turns remediation into queued work instead of immediate synchronous execution. Jobs are persisted, prioritized, delayed, retried, and executed asynchronously by worker loops. This means the operator loop does not block, jobs survive restarts, and follow-up workflow steps can be scheduled explicitly.

The scheduler is the orchestration layer that sits between decisioning and execution.

Key files:
- `k8s_operator/scheduler/scheduler.py` defines the async queue, worker loops, and result handling.
- `k8s_operator/scheduler/__init__.py` exports the scheduler API.
- `k8s_operator/state_store/store.py` persists queued and running jobs.

### Metrics Aggregator

The metrics aggregator collects time-windowed signals from incidents, job failures, logs, and events. It computes short-window and longer-window issue frequency, classifies trends, and marks services as unstable when repeated failures are observed.

This is what moves the system from event-driven remediation to trend-aware orchestration.

Key files:
- `k8s_operator/metrics/aggregator.py` builds `MetricsSnapshot` objects.
- `k8s_operator/metrics/__init__.py` exports the metrics API.
- `k8s_operator/utils/metrics.py` defines Prometheus gauges and counters.

### Config Manager

The config manager loads policy from YAML, validates it, and resolves per-issue or per-service overrides. It provides a defaults-first policy model with issue-level and service-level specialization. It also defines the workflows and breaker/retry policies used throughout the control plane.

This is the main control surface for changing behavior without redeploying the operator.

Key files:
- `k8s_operator/config_manager/manager.py` loads, validates, and resolves policy.
- `k8s_operator/config_manager/default_policy.yaml` contains the shipped defaults and workflows.
- `k8s_operator/config_manager/__init__.py` exports the policy models and manager.

### Workflow Engine

The workflow engine turns a decision into a multi-step remediation plan. A workflow may restart a pod, wait, scale up, roll back, or escalate across several steps. The engine serializes issue, diagnosis, and decision state into the job payload so the scheduler can resume or continue the workflow later.

This is what enables multi-step recovery rather than one-off remediation.

Key files:
- `k8s_operator/workflows/engine.py` defines workflow plans and payload building.
- `k8s_operator/workflows/__init__.py` exports workflow types.
- `k8s_operator/control_plane.py` chooses the workflow and schedules each step.

### State Store

The state store is a SQLite-backed persistence layer for incidents, diagnoses, decisions, jobs, and circuit breaker state. It provides the system history used by the decision engine and the metrics aggregator. It also gives the scheduler durable job storage so queued work is not lost on restart.

This is the memory of the autonomous control plane.

Key files:
- `k8s_operator/state_store/store.py` defines the schema and all persistence operations.
- `k8s_operator/state_store/__init__.py` exports the SQLite store.
- `k8s_operator/control_plane.py` records incidents, diagnoses, decisions, jobs, and outcomes.

## Running The Project

The main demo and control-plane entry points are in the Makefile and the demo shell script.

```bash
make demo              # Full local demo using the default provider
make demo-infra        # Create cluster + operator only
make demo-autonomous   # Show the autonomous control pipeline
make demo-scenario SCENARIO=oom-killed
make demo-watch        # Tail the control-plane logs
make demo-state        # Inspect jobs, incidents, breaker state
make demo-clean        # Delete the KIND cluster
make test              # Run the unit test suite
```

If Ollama is installed and the llama3 model is available, the operator uses real local inference. If not, it uses the built-in mock provider and still runs end-to-end with no external services.

## Notes On The Current Layout

- `k8s_operator/` is the canonical package.
- `operator/` remains in the tree as a compatibility namespace and historical copy of the earlier package layout.
- `demo_script.py` is a standalone experiment/demo harness and is separate from the main `scripts/demo.sh` entry point.
- The demo and the tests are fully local. If Ollama is absent, the project still runs using the built-in mock provider.
- The repository already includes the autonomous modules requested for the upgrade: decision engine, breaker, retry/backoff, scheduler, metrics aggregator, config manager, workflow engine, and state store.
