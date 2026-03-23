#!/bin/bash
# Show demo results summary

kubectl logs -n self-healing-system deployment/self-healing-operator 2>/dev/null | \
grep -E '("event":|strategy|confidence)' | \
grep -A 2 -B 2 'pod_issue_detected\|ai_diagnosis_completed\|remediation_successful' | \
sed 's/.*"event":"\([^"]*\)".*/  event: \1/g' | \
sed 's/.*"strategy":"\([^"]*\)".*/    → strategy: \1/g' | \
sed 's/.*"confidence":\([0-9.]*\).*/    → confidence: \1/g'
