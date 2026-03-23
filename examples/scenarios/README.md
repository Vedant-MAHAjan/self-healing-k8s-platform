# Example Scenarios

This directory contains example Kubernetes manifests that demonstrate various failure scenarios that the self-healing operator can detect and fix.

## Scenarios

### 1. CrashLoopBackOff
Simulates a pod that crashes immediately on startup.

```bash
kubectl apply -f crash-loop.yaml
```

### 2. OOMKilled
Simulates a pod that runs out of memory.

```bash
kubectl apply -f oom-killed.yaml
```

### 3. ImagePullBackOff
Simulates a deployment with an invalid image.

```bash
kubectl apply -f image-pull-error.yaml
```

### 4. MemoryLeak
Simulates a pod with increasing memory usage.

```bash
kubectl apply -f memory-leak.yaml
```

## Testing the Operator

1. Deploy one of the scenarios
2. Watch the operator logs:
   ```bash
   kubectl logs -f -n self-healing-system deployment/self-healing-operator
   ```
3. Observe the AI diagnosis and remediation
4. Check the metrics:
   ```bash
   kubectl port-forward -n self-healing-system svc/self-healing-operator-metrics 8000:8000
   curl localhost:8000/metrics
   ```

## Cleanup

```bash
kubectl delete -f .
```
