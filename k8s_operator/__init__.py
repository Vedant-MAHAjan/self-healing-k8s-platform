"""
Self-Healing Kubernetes Operator

An AI-powered Kubernetes operator that automatically detects and fixes
deployment issues.
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__description__ = "AI-powered self-healing Kubernetes operator"

from .config import Settings
from .models import (
    Issue,
    IssueType,
    Diagnosis,
    RemediationStrategy,
    RemediationStatus,
)

__all__ = [
    'Settings',
    'Issue',
    'IssueType',
    'Diagnosis',
    'RemediationStrategy',
    'RemediationStatus',
]
