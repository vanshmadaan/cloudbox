from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from ratelimit_core.exceptions import StorageBackendError
from ratelimit_core.metrics import record_backend_error, record_circuit_breaker_state
from ratelimit_core.storage.base import BaseStorageBackend
from ratelimit_core.storage.circuit_breaker import CircuitBreaker

logger = logging.getLogger("ratelimit_core.storage.redis")


class RedisStorageBackend(BaseStorageBackend):
    """
    Enterprise-ready Async Redis Storage Backend for distributed rate limiting.

    Features:
    - Supports standalone Redis, Redis Cluster, and Redis Sentinel topologies.
    - Full TLS/SSL encryption support (`rediss://`).
    - Integrated in-memory Circuit Breaker to eliminate latency degradation during outages.
    - Redis Cluster hash tags (`{...}`) to guarantee correct slot mapping.
    - Connection pooling tuning (max_connections, timeouts, health checks).
    - 12-factor cloud deployment via `from_env()`.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        redis_client: Optional[Union[aioredis.Redis, Any]] = None,
        fail_open: bool = False,
        key_prefix: str = "ratelimit",
        socket_timeout: float = 1.0,
        socket_connect_timeout: float = 1.0,
        cluster_mode: bool = False,
        cluster_nodes: Optional[List[str]] = None,
        sentinel_hosts: Optional[List[Tuple[str, int]]] = None,
        sentinel_service_name: str = "mymaster",
        sentinel_kwargs: Optional[Dict[str, Any]] = None,
        max_connections: Optional[int] = None,
        retry_on_timeout: bool = True,
        health_check_interval: int = 30,
        circuit_breaker_enabled: bool = True,
        circuit_breaker: Optional[CircuitBreaker] = None,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 10.0,
        **connection_kwargs: Any,
    ) -> None:
        self.redis_url = redis_url
        self.fail_open = fail_open
        self.key_prefix = key_prefix
        self.cluster_mode = cluster_mode
        self.cluster_nodes = cluster_nodes
        self.sentinel_hosts = sentinel_hosts
        self.sentinel_service_name = sentinel_service_name
        self.sentinel_kwargs = sentinel_kwargs or {}

        # Connection options
        self.connection_kwargs = connection_kwargs
        self.connection_kwargs.setdefault("socket_timeout", socket_timeout)
        self.connection_kwargs.setdefault("socket_connect_timeout", socket_connect_timeout)
        self.connection_kwargs.setdefault("retry_on_timeout", retry_on_timeout)
        self.connection_kwargs.setdefault("health_check_interval", health_check_interval)
        if max_connections is not None:
            self.connection_kwargs["max_connections"] = max_connections

        self._client: Optional[Union[aioredis.Redis, Any]] = redis_client
        self._owns_client: bool = redis_client is None
        self._script_shas: Dict[str, str] = {}

        # Circuit Breaker setup
        self.circuit_breaker_enabled = circuit_breaker_enabled
        self.circuit_breaker: Optional[CircuitBreaker]
        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        elif circuit_breaker_enabled:
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=circuit_failure_threshold,
                recovery_timeout=circuit_recovery_timeout,
                on_state_change=lambda state: record_circuit_breaker_state(
                    backend="redis",
                    state=state.value,
                ),
            )
        else:
            self.circuit_breaker = None

    @classmethod
    def from_env(cls, **overrides: Any) -> RedisStorageBackend:
        """
        Instantiate RedisStorageBackend from standard 12-factor cloud environment variables.
        """
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        fail_open = os.getenv("REDIS_FAIL_OPEN", "false").lower() in ("true", "1", "yes")
        key_prefix = os.getenv("REDIS_KEY_PREFIX", "ratelimit")
        socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "1.0"))
        socket_connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT", "1.0"))
        cluster_mode = os.getenv("REDIS_CLUSTER_MODE", "false").lower() in ("true", "1", "yes")

        cluster_nodes_env = os.getenv("REDIS_CLUSTER_NODES")
        cluster_nodes = (
            [node.strip() for node in cluster_nodes_env.split(",") if node.strip()]
            if cluster_nodes_env
            else None
        )

        sentinel_hosts_env = os.getenv("REDIS_SENTINEL_HOSTS")
        sentinel_hosts = None
        if sentinel_hosts_env:
            sentinel_hosts = []
            for h in sentinel_hosts_env.split(","):
                if ":" in h:
                    host, port_str = h.strip().split(":", 1)
                    sentinel_hosts.append((host, int(port_str)))

        sentinel_service = os.getenv("REDIS_SENTINEL_SERVICE_NAME", "mymaster")

        max_conn_env = os.getenv("REDIS_MAX_CONNECTIONS")
        max_connections = int(max_conn_env) if max_conn_env else None

        cb_enabled = os.getenv("REDIS_CIRCUIT_BREAKER", "true").lower() in ("true", "1", "yes")
        cb_failure_threshold = int(os.getenv("REDIS_CIRCUIT_FAILURE_THRESHOLD", "5"))
        cb_recovery_timeout = float(os.getenv("REDIS_CIRCUIT_RECOVERY_TIMEOUT", "10.0"))

        params: Dict[str, Any] = {
            "redis_url": redis_url,
            "fail_open": fail_open,
            "key_prefix": key_prefix,
            "socket_timeout": socket_timeout,
            "socket_connect_timeout": socket_connect_timeout,
            "cluster_mode": cluster_mode,
            "cluster_nodes": cluster_nodes,
            "sentinel_hosts": sentinel_hosts,
            "sentinel_service_name": sentinel_service,
            "max_connections": max_connections,
            "circuit_breaker_enabled": cb_enabled,
            "circuit_failure_threshold": cb_failure_threshold,
            "circuit_recovery_timeout": cb_recovery_timeout,
        }
        params.update(overrides)
        return cls(**params)

    def _prefixed_key(self, key: str) -> str:
        """
        Format key with prefix and cluster hash tag.
        Ensures related keys hash to the same Redis Cluster slot via `{...}`.
        """
        if not self.key_prefix:
            return key
        if "{" in key and "}" in key:
            return f"{self.key_prefix}:{key}"
        return f"{self.key_prefix}:{{{key}}}"

    def _create_client(self) -> Any:
        """Create the appropriate redis client based on topology configuration."""
        if self.cluster_mode or self.cluster_nodes:
            try:
                from redis.asyncio.cluster import RedisCluster
            except ImportError as e:
                raise StorageBackendError("Redis cluster mode requires redis>=5.0.0") from e

            nodes = self.cluster_nodes or [self.redis_url]
            return RedisCluster.from_url(
                nodes[0] if nodes else self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                **self.connection_kwargs,
            )

        if self.sentinel_hosts:
            try:
                from redis.asyncio.sentinel import Sentinel
            except ImportError as e:
                raise StorageBackendError("Redis Sentinel requires redis>=5.0.0") from e

            sentinel = Sentinel(
                self.sentinel_hosts,
                encoding="utf-8",
                decode_responses=True,
                sentinel_kwargs=self.sentinel_kwargs,
                **self.connection_kwargs,
            )
            return sentinel.master_for(self.sentinel_service_name)

        return aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            **self.connection_kwargs,
        )

    async def initialize(self) -> None:
        if self._client is None:
            self._client = self._create_client()

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._create_client()
        return self._client

    async def eval_script(
        self,
        script: str,
        keys: List[str],
        args: List[Any],
    ) -> Any:
        # Check circuit breaker
        if self.circuit_breaker and not (await self.circuit_breaker.can_execute()):
            logger.warning("Redis Circuit Breaker is OPEN; short-circuiting eval_script call.")
            if self.fail_open:
                # [allowed=1, remaining=1, reset_after=0, retry_after=0]
                return [1, 1, "0", "0"]
            raise StorageBackendError("Redis Circuit Breaker is OPEN: backend is unavailable")

        prefixed_keys = [self._prefixed_key(k) for k in keys]
        try:
            # Check if sha cached
            sha = self._script_shas.get(script)
            if sha is not None:
                try:
                    result = await self.client.evalsha(sha, len(prefixed_keys), *prefixed_keys, *args)
                    if self.circuit_breaker:
                        await self.circuit_breaker.record_success()
                    return result
                except RedisError as e:
                    if "NOSCRIPT" not in str(e):
                        raise

            # Register script or run direct eval
            try:
                sha = await self.client.script_load(script)
                self._script_shas[script] = sha
                result = await self.client.evalsha(sha, len(prefixed_keys), *prefixed_keys, *args)
                if self.circuit_breaker:
                    await self.circuit_breaker.record_success()
                return result
            except RedisError:
                # Fallback to direct eval if script_load fails
                result = await self.client.eval(script, len(prefixed_keys), *prefixed_keys, *args)
                if self.circuit_breaker:
                    await self.circuit_breaker.record_success()
                return result

        except RedisError as exc:
            logger.error("Redis error executing script: %s", exc, exc_info=True)
            record_backend_error("redis", "eval_script")
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure(exc)

            if self.fail_open:
                return [1, 1, "0", "0"]
            raise StorageBackendError(f"Redis script execution failed: {exc}") from exc

    async def get(self, key: str) -> Optional[str]:
        if self.circuit_breaker and not (await self.circuit_breaker.can_execute()):
            logger.warning("Redis Circuit Breaker is OPEN; short-circuiting get call.")
            if self.fail_open:
                return None
            raise StorageBackendError("Redis Circuit Breaker is OPEN: backend is unavailable")

        try:
            res = await self.client.get(self._prefixed_key(key))
            if self.circuit_breaker:
                await self.circuit_breaker.record_success()
            if res is None:
                return None
            return res.decode() if isinstance(res, bytes) else str(res)
        except RedisError as exc:
            logger.error("Redis error in get: %s", exc)
            record_backend_error("redis", "get")
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure(exc)
            if self.fail_open:
                return None
            raise StorageBackendError(f"Redis get failed: {exc}") from exc

    async def set(
        self,
        key: str,
        value: str,
        expire_seconds: Optional[float] = None,
    ) -> None:
        if self.circuit_breaker and not (await self.circuit_breaker.can_execute()):
            logger.warning("Redis Circuit Breaker is OPEN; short-circuiting set call.")
            if self.fail_open:
                return
            raise StorageBackendError("Redis Circuit Breaker is OPEN: backend is unavailable")

        try:
            px = int(expire_seconds * 1000) if expire_seconds else None
            await self.client.set(self._prefixed_key(key), value, px=px)
            if self.circuit_breaker:
                await self.circuit_breaker.record_success()
        except RedisError as exc:
            logger.error("Redis error in set: %s", exc)
            record_backend_error("redis", "set")
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure(exc)
            if not self.fail_open:
                raise StorageBackendError(f"Redis set failed: {exc}") from exc

    async def delete(self, key: str) -> bool:
        if self.circuit_breaker and not (await self.circuit_breaker.can_execute()):
            logger.warning("Redis Circuit Breaker is OPEN; short-circuiting delete call.")
            if self.fail_open:
                return False
            raise StorageBackendError("Redis Circuit Breaker is OPEN: backend is unavailable")

        try:
            res = await self.client.delete(self._prefixed_key(key))
            if self.circuit_breaker:
                await self.circuit_breaker.record_success()
            return bool(res > 0)
        except RedisError as exc:
            logger.error("Redis error in delete: %s", exc)
            record_backend_error("redis", "delete")
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure(exc)
            if not self.fail_open:
                raise StorageBackendError(f"Redis delete failed: {exc}") from exc
            return False

    async def flush_all(self) -> None:
        if self.circuit_breaker and not (await self.circuit_breaker.can_execute()):
            logger.warning("Redis Circuit Breaker is OPEN; short-circuiting flush_all call.")
            if self.fail_open:
                return
            raise StorageBackendError("Redis Circuit Breaker is OPEN: backend is unavailable")

        try:
            await self.client.flushdb()
            if self.circuit_breaker:
                await self.circuit_breaker.record_success()
        except RedisError as exc:
            logger.error("Redis error in flush_all: %s", exc)
            record_backend_error("redis", "flush_all")
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure(exc)
            if not self.fail_open:
                raise StorageBackendError(f"Redis flushdb failed: {exc}") from exc
