"""
Configuration management for the self-healing operator.
Uses environment variables with sensible defaults.

Demo-friendly defaults:
- ai_provider = "ollama" (real AI, free) or "mock" (no setup)
- auto_approve_fixes = True (for demo)
- dry_run = False (actually apply fixes)
"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Operator configuration settings."""
    
    # Operator settings
    dry_run: bool = Field(
        default=False,
        description="If true, only log actions without applying them"
    )
    
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    
    operator_namespace: str = Field(
        default="self-healing-system",
        description="Namespace where the operator is deployed"
    )
    
    # AI Configuration - Default to Ollama (free local LLM)
    ai_provider: str = Field(
        default="ollama",
        description="AI provider: ollama (free, recommended), mock, openai, or anthropic"
    )
    
    # Ollama settings (FREE local LLM!)
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL"
    )
    
    ollama_model: str = Field(
        default="llama3",
        description="Ollama model (llama3, mistral, codellama, etc.)"
    )
    
    # OpenAI settings (optional, costs money)
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key (optional)"
    )
    
    openai_model: str = Field(
        default="gpt-4-turbo-preview",
        description="OpenAI model to use"
    )
    
    # Anthropic settings (optional, costs money)
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic API key (optional)"
    )
    
    anthropic_model: str = Field(
        default="claude-3-opus-20240229",
        description="Anthropic model to use"
    )
    
    ai_timeout: int = Field(
        default=60,
        description="Timeout for AI requests in seconds"
    )
    
    ai_max_retries: int = Field(
        default=3,
        description="Maximum retries for AI requests"
    )
    
    # Remediation settings - Demo-friendly defaults
    auto_approve_fixes: bool = Field(
        default=True,
        description="Automatically apply fixes (True for demo)"
    )
    
    max_remediation_retries: int = Field(
        default=3,
        description="Maximum remediation attempts per issue"
    )
    
    remediation_cooldown: int = Field(
        default=60,
        description="Cooldown period in seconds between remediation attempts"
    )
    
    enable_pod_restart: bool = Field(
        default=True,
        description="Enable automatic pod restart remediation"
    )
    
    enable_scaling: bool = Field(
        default=True,
        description="Enable automatic scaling remediation"
    )
    
    enable_rollback: bool = Field(
        default=True,
        description="Enable automatic deployment rollback"
    )
    
    # Prometheus settings
    alertmanager_url: str = Field(
        default="http://alertmanager:9093",
        description="Alertmanager URL for receiving alerts"
    )
    
    prometheus_url: str = Field(
        default="http://prometheus:9090",
        description="Prometheus URL for querying metrics"
    )
    
    # Metrics
    metrics_port: int = Field(
        default=8000,
        description="Port for exposing Prometheus metrics"
    )
    
    # Resource limits for analysis
    max_log_lines: int = Field(
        default=500,
        description="Maximum log lines to fetch for analysis"
    )
    
    max_events_lookback: int = Field(
        default=100,
        description="Maximum number of events to analyze"
    )
    
    # ArgoCD Integration
    argocd_enabled: bool = Field(
        default=False,
        description="Enable ArgoCD integration"
    )
    
    argocd_server: Optional[str] = Field(
        default=None,
        description="ArgoCD server URL"
    )
    
    argocd_token: Optional[str] = Field(
        default=None,
        description="ArgoCD authentication token"
    )
    
    class Config:
        env_prefix = "OPERATOR_"
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()
