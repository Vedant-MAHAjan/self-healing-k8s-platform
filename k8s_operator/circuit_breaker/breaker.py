"""Per-service circuit breaker used to avoid cascading failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional

import structlog

from ..config_manager import CircuitBreakerPolicy
from ..state_store import SQLiteStateStore
from ..utils.metrics import circuit_breaker_state_gauge


logger = structlog.get_logger()


class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerSnapshot:
    key: str
    state: CircuitBreakerState
    failure_count: int = 0
    success_count: int = 0
    opened_until: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


class CircuitBreaker:
    """Stateful circuit breaker with persisted state."""

    def __init__(self, state_store: SQLiteStateStore):
        self.state_store = state_store

    async def allow(self, breaker_key: str, policy: CircuitBreakerPolicy) -> bool:
        snapshot = await self.get_snapshot(breaker_key)

        if snapshot.state == CircuitBreakerState.CLOSED:
            return True

        if snapshot.state == CircuitBreakerState.OPEN:
            if snapshot.opened_until and _utcnow() < snapshot.opened_until:
                logger.warning(
                    "circuit_breaker_open",
                    key=breaker_key,
                    opened_until=snapshot.opened_until.isoformat(),
                )
                return False

            await self._persist_snapshot(
                CircuitBreakerSnapshot(
                    key=breaker_key,
                    state=CircuitBreakerState.HALF_OPEN,
                    failure_count=snapshot.failure_count,
                    success_count=snapshot.success_count,
                    metadata={"probe": True},
                )
            )
            logger.info("circuit_breaker_half_open", key=breaker_key)
            return True

        return True

    async def record_success(self, breaker_key: str) -> None:
        snapshot = await self.get_snapshot(breaker_key)
        snapshot.state = CircuitBreakerState.CLOSED
        snapshot.failure_count = 0
        snapshot.success_count += 1
        snapshot.opened_until = None
        snapshot.last_success_at = _utcnow()
        snapshot.metadata = {**snapshot.metadata, "last_event": "success"}
        await self._persist_snapshot(snapshot)
        logger.info("circuit_breaker_closed", key=breaker_key)

    async def record_failure(
        self,
        breaker_key: str,
        policy: CircuitBreakerPolicy,
        reason: Optional[str] = None,
    ) -> None:
        snapshot = await self.get_snapshot(breaker_key)
        snapshot.failure_count += 1
        snapshot.last_failure_at = _utcnow()
        snapshot.metadata = {**snapshot.metadata, "last_event": "failure", "reason": reason}

        if snapshot.state == CircuitBreakerState.HALF_OPEN or snapshot.failure_count >= policy.failure_threshold:
            snapshot.state = CircuitBreakerState.OPEN
            snapshot.opened_until = _utcnow() + timedelta(seconds=policy.recovery_timeout_seconds)
            logger.warning(
                "circuit_breaker_opened",
                key=breaker_key,
                failure_count=snapshot.failure_count,
                opened_until=snapshot.opened_until.isoformat() if snapshot.opened_until else None,
            )
        else:
            snapshot.state = CircuitBreakerState.CLOSED

        await self._persist_snapshot(snapshot)

    async def get_snapshot(self, breaker_key: str) -> CircuitBreakerSnapshot:
        state = await self.state_store.get_breaker_state(breaker_key)
        if not state:
            return CircuitBreakerSnapshot(key=breaker_key, state=CircuitBreakerState.CLOSED)

        return CircuitBreakerSnapshot(
            key=breaker_key,
            state=CircuitBreakerState(state.get("state", CircuitBreakerState.CLOSED.value)),
            failure_count=int(state.get("failure_count", 0)),
            success_count=int(state.get("success_count", 0)),
            opened_until=_parse_dt(state.get("opened_until")),
            last_failure_at=_parse_dt(state.get("last_failure_at")),
            last_success_at=_parse_dt(state.get("last_success_at")),
            metadata=state.get("metadata", {}),
        )

    async def _persist_snapshot(self, snapshot: CircuitBreakerSnapshot) -> None:
        state_value = {
            CircuitBreakerState.CLOSED: 0,
            CircuitBreakerState.HALF_OPEN: 1,
            CircuitBreakerState.OPEN: 2,
        }[snapshot.state]
        circuit_breaker_state_gauge.labels(breaker_key=snapshot.key).set(state_value)
        await self.state_store.record_breaker_state(
            snapshot.key,
            {
                "state": snapshot.state.value,
                "failure_count": snapshot.failure_count,
                "success_count": snapshot.success_count,
                "opened_until": snapshot.opened_until,
                "last_failure_at": snapshot.last_failure_at,
                "last_success_at": snapshot.last_success_at,
                "metadata": snapshot.metadata,
            },
        )