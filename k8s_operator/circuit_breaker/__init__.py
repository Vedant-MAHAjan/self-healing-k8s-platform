"""Failure isolation and circuit breaking for remediation."""

from .breaker import CircuitBreaker, CircuitBreakerState, CircuitBreakerSnapshot

__all__ = ["CircuitBreaker", "CircuitBreakerState", "CircuitBreakerSnapshot"]