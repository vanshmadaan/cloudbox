from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("ratelimit_core.circuit_breaker")


class CircuitState(str, Enum):
    """Lifecycle states of the Circuit Breaker."""
    CLOSED = "closed"        # Normal operation: requests pass to backend
    OPEN = "open"            # Backend down: requests fail fast or fail open without network I/O
    HALF_OPEN = "half_open"  # Probing: testing if backend has recovered


class CircuitBreaker:
    """
    Asynchronous, thread-safe Circuit Breaker for distributed storage backends.

    Prevents cascading latency spikes and ASGI thread exhaustion during Redis outages
    by failing fast or failing open in 0ms without waiting on socket timeouts.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 10.0,
        half_open_success_threshold: int = 2,
        on_state_change: Optional[Callable[[CircuitState], None]] = None,
    ) -> None:
        """
        Args:
            failure_threshold: Number of consecutive failures before opening the circuit.
            recovery_timeout: Seconds to wait in OPEN state before testing recovery in HALF_OPEN.
            half_open_success_threshold: Consecutive successful probes required to close the circuit.
            on_state_change: Optional hook called whenever the circuit state transitions.
        """
        if failure_threshold <= 0:
            raise ValueError(f"failure_threshold must be > 0, got {failure_threshold}")
        if recovery_timeout <= 0:
            raise ValueError(f"recovery_timeout must be > 0, got {recovery_timeout}")
        if half_open_success_threshold <= 0:
            raise ValueError(f"half_open_success_threshold must be > 0, got {half_open_success_threshold}")

        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Returns the current state, dynamically evaluating recovery timeout."""
        if self._state == CircuitState.OPEN:
            now = time.monotonic()
            if (now - self._last_failure_time) >= self.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    def _transition_to(self, new_state: CircuitState) -> None:
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            logger.warning(
                "Circuit breaker state changed: %s -> %s",
                old_state.value,
                new_state.value,
            )
            if self.on_state_change is not None:
                try:
                    self.on_state_change(new_state)
                except Exception as e:
                    logger.debug("Error in circuit breaker on_state_change callback: %s", e)

    async def can_execute(self) -> bool:
        """
        Determines whether a call to the storage backend should be attempted.
        Returns True if CLOSED or HALF_OPEN (probe allowed).
        Returns False if OPEN.
        """
        async with self._lock:
            current = self.state
            return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def can_execute_sync(self) -> bool:
        """Synchronous check of whether execution can proceed."""
        current = self.state
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    async def record_success(self) -> None:
        """Record a successful backend operation."""
        async with self._lock:
            current = self.state
            if current == CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self.half_open_success_threshold:
                    self._consecutive_failures = 0
                    self._consecutive_successes = 0
                    self._transition_to(CircuitState.CLOSED)
            elif current == CircuitState.CLOSED:
                self._consecutive_failures = 0

    async def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record a failed backend operation (e.g. Redis connection error or timeout)."""
        async with self._lock:
            self._last_failure_time = time.monotonic()
            current = self.state
            if current == CircuitState.HALF_OPEN:
                # Probe failed; immediately trip back to OPEN
                self._consecutive_successes = 0
                self._transition_to(CircuitState.OPEN)
            elif current == CircuitState.CLOSED:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.failure_threshold:
                    self._consecutive_successes = 0
                    self._transition_to(CircuitState.OPEN)

    async def reset(self) -> None:
        """Force reset the circuit breaker back to CLOSED."""
        async with self._lock:
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._last_failure_time = 0.0
            self._transition_to(CircuitState.CLOSED)
