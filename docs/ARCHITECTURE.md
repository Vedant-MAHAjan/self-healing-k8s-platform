# Architecture

This document describes the architecture of the Self-Healing Kubernetes Operator.

## Autonomous Control Plane (Current)

The operator now wraps the original event-driven remediation loop with a policy-driven,
stateful orchestration layer. Detection and AI diagnosis still feed the system, but
actions now flow through decisioning, retries, scheduling, and persistent state.

```
Metrics Aggregator
   ↓
Detection Layer (Kopf handlers)
   ↓
AI Diagnosis Engine
   ↓
Decision Engine (policy-driven)
   ↓
Circuit Breaker (per-service)
   ↓
Retry + Backoff Engine
   ↓
Job Scheduler (queued + delayed jobs)
   ↓
Execution Layer (existing remediation strategies)
   ↓
Feedback + State Store (SQLite)
```

### What Changed

- **Decision Engine**: Selects immediate remediation, delay-and-retry, escalation, or manual review.
- **Job Scheduler**: Persists jobs and executes them asynchronously instead of blocking the handler loop.
- **Retry + Backoff**: Exponential backoff with jitter and max-retry enforcement.
- **Circuit Breaker**: Stops repeated failures from cascading across the same service.
- **Metrics Aggregator**: Uses time-window incident trends, not just single events.
- **State Store**: Stores incidents, diagnoses, decisions, jobs, and breaker state in SQLite.

The older event-driven sections below describe the original baseline components that are still reused by the new control plane.

## Overview

The operator consists of several key components that work together to detect, diagnose, and remediate Kubernetes issues automatically using AI.

```
┌─────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                       │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │  Pods    │  │Deployments│  │  Events  │                 │
│  └────┬─────┘  └────┬──────┘  └────┬─────┘                 │
│       │             │              │                        │
│       └─────────────┴──────────────┘                        │
│                     │                                       │
└─────────────────────┼───────────────────────────────────────┘
                      │
          ┌───────────▼──────────────┐
          │   Prometheus / Metrics   │
          │   ┌──────────────────┐   │
          │   │  Alert Rules     │   │
          │   └────────┬─────────┘   │
          └────────────┼─────────────┘
                       │
          ┌────────────▼─────────────┐
          │    Alertmanager          │
          │   (Routes alerts)        │
          └────────────┬─────────────┘
                       │
          ┌────────────▼─────────────────────────────────┐
          │    Self-Healing Operator                     │
          │                                              │
          │  ┌────────────────────────────────────────┐ │
          │  │  1. Event Handlers (Kopf)             │ │
          │  │     - Pod events                       │ │
          │  │     - Deployment events                │ │
          │  │     - Alert webhook receiver           │ │
          │  └──────────┬─────────────────────────────┘ │
          │             │                                │
          │  ┌──────────▼─────────────────────────────┐ │
          │  │  2. Issue Detection                    │ │
          │  │     - Parse pod status                 │ │
          │  │     - Fetch logs & events              │ │
          │  │     - Classify issue type              │ │
          │  └──────────┬─────────────────────────────┘ │
          │             │                                │
          │  ┌──────────▼─────────────────────────────┐ │
          │  │  3. AI Diagnosis Engine                │ │
          │  │     - Build context prompt             │ │
          │  │     - Call LLM (OpenAI/Anthropic)      │ │
          │  │     - Parse diagnosis response         │ │
          │  │     - Select remediation strategy      │ │
          │  └──────────┬─────────────────────────────┘ │
          │             │                                │
          │  ┌──────────▼─────────────────────────────┐ │
          │  │  4. Strategy Manager                   │ │
          │  │     - Validate strategy                │ │
          │  │     - Check permissions                │ │
          │  │     - Execute remediation              │ │
          │  └──────────┬─────────────────────────────┘ │
          │             │                                │
          │  ┌──────────▼─────────────────────────────┐ │
          │  │  5. Remediation Strategies             │ │
          │  │     - restart_pod()                    │ │
          │  │     - scale_up()                       │ │
          │  │     - rollback_deployment()            │ │
          │  │     - increase_resources()             │ │
          │  └──────────┬─────────────────────────────┘ │
          │             │                                │
          │  ┌──────────▼─────────────────────────────┐ │
          │  │  6. Kubernetes API                     │ │
          │  │     - Apply fixes                      │ │
          │  │     - Update resources                 │ │
          │  └────────────────────────────────────────┘ │
          │                                              │
          │  ┌────────────────────────────────────────┐ │
          │  │  Observability                         │ │
          │  │  - Prometheus metrics                  │ │
          │  │  - Structured logging                  │ │
          │  │  - Audit trail                         │ │
          │  └────────────────────────────────────────┘ │
          └──────────────────────────────────────────────┘

```

## Components

### 1. Event Handlers (kopf-based)

- **Pod Handler**: Monitors pod events (create, update, delete)
- **Deployment Handler**: Tracks deployment rollouts and failures
- **Alert Receiver**: HTTP webhook endpoint for Prometheus alerts

### 2. Issue Detection

Detects various issue types:
- CrashLoopBackOff
- ImagePullBackOff
- OOMKilled
- Memory leaks (via metrics)
- Health check failures
- Pod pending/unschedulable

### 3. AI Diagnosis Engine

**Providers:**
- OpenAI (GPT-4)
- Anthropic (Claude)
- Fallback to rule-based

**Process:**
1. Build comprehensive prompt with:
   - Issue details
   - Pod/deployment status
   - Container logs (last N lines)
   - Recent events
   - Metrics (if available)

2. Send to LLM with structured output request
3. Parse JSON response:
   - Root cause analysis
   - Recommended strategy
   - Confidence score
   - Alternative strategies
   - Reasoning

4. Fallback to rule-based if AI fails

### 4. Strategy Manager

**Responsibilities:**
- Validate recommended strategy
- Check if strategy is enabled
- Track remediation attempts
- Apply cooldown periods
- Execute strategy with retry logic

### 5. Remediation Strategies

| Strategy | Use Case | Actions |
|----------|----------|---------|
| `restart_pod` | Crash loops, hangs | Delete pod (recreated by controller) |
| `scale_up` | Memory leaks, high load | Increase replica count |
| `scale_down` | Over-provisioning | Decrease replica count |
| `rollback_deployment` | Bad deployments | Revert to previous version |
| `increase_resources` | OOMKilled | Increase memory/CPU limits |
| `evict_pod` | Node pressure | Graceful eviction |

### 6. Observability

**Metrics (Prometheus):**
- `self_healing_alerts_received_total`
- `self_healing_fixes_applied_total`
- `self_healing_fixes_failed_total`
- `self_healing_ai_diagnosis_duration_seconds`
- `self_healing_active_issues`

**Logging:**
- Structured JSON logs
- Correlation IDs for tracking
- Detailed error traces

## Data Flow

1. **Issue Detection**
   ```
   Kubernetes Event/Alert → Handler → Issue Model
   ```

2. **Enrichment**
   ```
   Issue → Fetch Logs/Events → Enriched Issue
   ```

3. **Diagnosis**
   ```
   Enriched Issue → AI Engine → Diagnosis (with strategy)
   ```

4. **Remediation**
   ```
   Diagnosis → Strategy Manager → Execute Strategy → Update K8s
   ```

5. **Feedback Loop**
   ```
   Execution Result → Metrics/Logs → Monitoring
   ```

## Configuration

All configuration via environment variables:
- Operator settings (dry run, log level)
- AI provider configuration
- Remediation policies
- Integration endpoints (Prometheus, ArgoCD)

## Security

- **RBAC**: Least-privilege service account
- **Secrets**: API keys stored in Kubernetes secrets
- **Audit**: All actions logged with details
- **Dry Run**: Test mode for validation
- **Manual Approval**: Optional approval workflow

## Scalability

- Single replica (leader election not required for MVP)
- Stateless design
- Cooldown prevents remediation storms
- Configurable retry limits

## Future Enhancements

1. **Multi-cluster support**
2. **Custom CRD for remediation policies**
3. **Webhook admission controller**
4. **Machine learning for pattern detection**
5. **Integration with incident management (PagerDuty, etc.)**
6. **Advanced rollback strategies (canary, blue-green)**
7. **Cost optimization recommendations**
