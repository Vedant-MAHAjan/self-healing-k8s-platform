"""
Prompt templates for AI diagnosis.
"""

from healing_operator.models import Issue, IssueType


DIAGNOSIS_SYSTEM_PROMPT = """You are an expert Kubernetes Site Reliability Engineer (SRE) and platform engineer.
Your role is to diagnose Kubernetes pod and deployment issues and recommend remediation strategies.

You will be provided with:
- Issue description and type
- Pod status and metadata
- Container logs (if available)
- Recent Kubernetes events
- Resource metrics (if available)

Your task is to:
1. Analyze the root cause of the issue
2. Recommend the best remediation strategy
3. Provide reasoning for your recommendation

Available remediation strategies:
- restart_pod: Restart the problematic pod
- scale_up: Increase the number of replicas
- scale_down: Decrease the number of replicas
- rollback_deployment: Rollback to the previous deployment version
- increase_resources: Increase CPU or memory limits
- evict_pod: Evict and reschedule the pod
- no_action: No action needed, issue is transient
- manual_intervention: Requires manual investigation

You must respond with ONLY a valid JSON object in this exact format:
{
    "root_cause": "Brief description of the root cause",
    "analysis": "Detailed analysis of the issue",
    "recommended_strategy": "one of the strategies listed above",
    "confidence": 0.85,
    "reasoning": "Explanation of why this strategy is recommended",
    "alternative_strategies": ["list", "of", "alternative", "strategies"],
    "requires_manual_intervention": false,
    "suggested_actions": ["Additional manual steps if needed"]
}

Be concise but thorough. Confidence should be between 0.0 and 1.0.
"""


def build_diagnosis_prompt(issue: Issue) -> str:
    """
    Build the diagnosis prompt for the AI based on the issue.
    
    Args:
        issue: The issue to diagnose
        
    Returns:
        Formatted prompt string
    """
    prompt_parts = [
        "# Kubernetes Issue Diagnosis Request",
        "",
        f"## Issue Information",
        f"- **Issue ID**: {issue.issue_id}",
        f"- **Type**: {issue.issue_type.value}",
        f"- **Severity**: {issue.severity}",
        f"- **Resource**: {issue.resource_kind}/{issue.resource_name}",
        f"- **Namespace**: {issue.resource_namespace}",
        f"- **Description**: {issue.description}",
        f"- **Detected At**: {issue.detected_at}",
        "",
    ]
    
    # Add pod information if available
    if issue.pod_info:
        pod = issue.pod_info
        prompt_parts.extend([
            "## Pod Information",
            f"- **Name**: {pod.name}",
            f"- **Status**: {pod.status}",
            f"- **Restart Count**: {pod.restart_count}",
            f"- **Node**: {pod.node_name or 'N/A'}",
            "",
            "### Container Statuses",
        ])
        
        for idx, container in enumerate(pod.container_statuses, 1):
            container_name = container.get('name', 'unknown')
            state = container.get('state', {})
            
            # Extract state details
            if 'running' in state:
                state_info = f"Running (started: {state['running'].get('startedAt', 'N/A')})"
            elif 'waiting' in state:
                reason = state['waiting'].get('reason', 'Unknown')
                message = state['waiting'].get('message', '')
                state_info = f"Waiting - {reason}: {message}"
            elif 'terminated' in state:
                reason = state['terminated'].get('reason', 'Unknown')
                exit_code = state['terminated'].get('exitCode', 'N/A')
                state_info = f"Terminated - {reason} (exit code: {exit_code})"
            else:
                state_info = "Unknown"
            
            prompt_parts.append(f"{idx}. **{container_name}**: {state_info}")
        
        prompt_parts.append("")
    
    # Add deployment information if available
    if issue.deployment_info:
        deploy = issue.deployment_info
        prompt_parts.extend([
            "## Deployment Information",
            f"- **Name**: {deploy.name}",
            f"- **Replicas**: {deploy.replicas}",
            f"- **Ready Replicas**: {deploy.ready_replicas}",
            f"- **Available Replicas**: {deploy.available_replicas}",
            f"- **Revision**: {deploy.revision or 'N/A'}",
            "",
        ])
    
    # Add logs if available (limit to important lines)
    if issue.logs:
        prompt_parts.extend([
            "## Recent Logs (last 50 lines)",
            "```",
        ])
        
        # Take last 50 lines
        log_lines = issue.logs[-50:] if len(issue.logs) > 50 else issue.logs
        prompt_parts.extend(log_lines)
        prompt_parts.extend(["```", ""])
    
    # Add events if available
    if issue.events:
        prompt_parts.extend([
            "## Recent Events",
        ])
        
        # Take last 10 events
        recent_events = issue.events[-10:] if len(issue.events) > 10 else issue.events
        for event in recent_events:
            event_type = event.get('type', 'Normal')
            reason = event.get('reason', 'Unknown')
            message = event.get('message', '')
            timestamp = event.get('lastTimestamp', event.get('eventTime', 'N/A'))
            
            prompt_parts.append(
                f"- [{timestamp}] **{event_type}** - {reason}: {message}"
            )
        
        prompt_parts.append("")
    
    # Add metrics if available
    if issue.metrics:
        prompt_parts.extend([
            "## Metrics",
        ])
        for metric_name, metric_value in issue.metrics.items():
            prompt_parts.append(f"- **{metric_name}**: {metric_value}")
        prompt_parts.append("")
    
    # Add alert labels if from Prometheus
    if issue.alert_labels:
        prompt_parts.extend([
            "## Alert Labels",
        ])
        for label, value in issue.alert_labels.items():
            prompt_parts.append(f"- **{label}**: {value}")
        prompt_parts.append("")
    
    prompt_parts.extend([
        "---",
        "",
        "Please analyze this issue and provide a diagnosis in the required JSON format.",
    ])
    
    return "\n".join(prompt_parts)


def build_chat_messages(issue: Issue):
    """
    Build chat messages for providers that use chat format.
    
    Returns:
        List of message dicts
    """
    return [
        {
            "role": "system",
            "content": DIAGNOSIS_SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": build_diagnosis_prompt(issue)
        }
    ]
