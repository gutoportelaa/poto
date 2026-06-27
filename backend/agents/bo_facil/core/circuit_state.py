"""Shared state for circuit breaker and thread degradation.

When `settings.REDIS_URL` is set, state is persisted in Redis so all
workers share the same view (a failure in worker A propagates to B).
When unset, falls back to in-process state — useful for tests and
single-worker dev.

The Redis backend never raises to the caller: any Redis error logs a
warning and degrades to in-memory for that call. The agent never blocks
on Redis problems.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from core import runtime_settings, settings

logger = logging.getLogger(__name__)

# Local fallback state — used when Redis is unavailable or not configured.
_local_degraded: dict[str, float] = {}
_local_failures: deque[float] = deque(maxlen=50)
_local_circuit_open_until: float = 0.0

# Single-shot health probe scheduled at circuit-open time.
# Holds an in-process reference so a subsequent open can cancel/supersede it.
_pending_probe: asyncio.Task[None] | None = None
_PROBE_LOCK_KEY = "llm:circuit:probe_lock"
_PROBE_LEAD_SECONDS = 5.0  # fire probe this long before TTL would expire

_redis_client = None  # lazy init; type: redis.asyncio.Redis | None
_redis_unavailable_logged = False

# Meta-circuit-breaker for Redis itself: after a Redis op fails, skip Redis
# entirely for REDIS_BACKOFF_SECONDS to avoid paying socket_timeout per call
# while Redis is slow/down. We re-probe after the backoff expires.
_redis_unavailable_until: float = 0.0
REDIS_BACKOFF_SECONDS = 30.0
# Aggressive socket timeout: Redis intra-VPC P95 is <5ms; >200ms means trouble.
REDIS_SOCKET_TIMEOUT = 0.2


def _mark_redis_unavailable(reason: str) -> None:
    """Backoff Redis after a failure to avoid paying its timeout repeatedly."""
    global _redis_unavailable_until
    _redis_unavailable_until = time.monotonic() + REDIS_BACKOFF_SECONDS
    logger.warning(
        f"Redis disabled for {REDIS_BACKOFF_SECONDS:.0f}s (in-memory fallback active): {reason}"
    )


def _get_redis():
    """Lazily build an async Redis client. Returns None if disabled or unconfigured."""
    global _redis_client, _redis_unavailable_logged
    # Backoff window active → skip Redis entirely
    if time.monotonic() < _redis_unavailable_until:
        return None
    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
        )
        return _redis_client
    except Exception as e:
        if not _redis_unavailable_logged:
            logger.warning(f"Redis client init failed, using in-memory fallback: {e}")
            _redis_unavailable_logged = True
        _mark_redis_unavailable(str(e))
        return None


# ─── Thread degradation ──────────────────────────────────────────────────────

_THREAD_PREFIX = "llm:thread:degraded:"


async def is_thread_degraded(thread_id: str | None) -> bool:
    if not thread_id:
        return False
    client = _get_redis()
    if client is not None:
        try:
            return bool(await client.exists(_THREAD_PREFIX + thread_id))
        except Exception as e:
            _mark_redis_unavailable(f"is_thread_degraded: {e}")
    if thread_id not in _local_degraded:
        return False
    elapsed = time.monotonic() - _local_degraded[thread_id]
    if elapsed > runtime_settings.resolve("DEGRADED_THREAD_TTL"):
        del _local_degraded[thread_id]
        return False
    return True


async def mark_thread_degraded(thread_id: str | None) -> None:
    if not thread_id:
        return
    ttl = int(runtime_settings.resolve("DEGRADED_THREAD_TTL"))
    client = _get_redis()
    if client is not None:
        try:
            await client.set(_THREAD_PREFIX + thread_id, "1", ex=ttl)
            return
        except Exception as e:
            _mark_redis_unavailable(f"mark_thread_degraded: {e}")
    _local_degraded[thread_id] = time.monotonic()


# ─── Global circuit breaker ──────────────────────────────────────────────────

_CIRCUIT_OPEN_KEY = "llm:circuit:open_until"
_FAILURES_KEY = "llm:circuit:failures"


async def is_circuit_open() -> bool:
    client = _get_redis()
    if client is not None:
        try:
            value = await client.get(_CIRCUIT_OPEN_KEY)
            is_open = value is not None  # key existence with TTL == circuit open
            if is_open:
                await _ensure_probe_armed(client)
            return is_open
        except Exception as e:
            _mark_redis_unavailable(f"is_circuit_open: {e}")
    return time.monotonic() < _local_circuit_open_until


async def _ensure_probe_armed(client) -> None:
    """Arm a local probe when this worker observes a stuck-open circuit.

    Why: ``_schedule_probe`` is called only by the worker that opens the
    circuit. If that worker restarts (deploy, OOM, scale-down) the local
    task is lost — Redis still says "open" but nobody probes for recovery.
    Any subsequent worker reading "open" via :func:`is_circuit_open` now
    self-arms its own probe, sleeping until ~PROBE_LEAD_SECONDS before the
    Redis TTL would expire. Cross-worker execution dedup is handled by the
    SETNX lock inside ``_probe_at_expiry``.
    """
    global _pending_probe
    if _pending_probe is not None and not _pending_probe.done():
        return
    if not runtime_settings.resolve("HEALTH_PROBE_ENABLED"):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    try:
        ttl_ms = await client.pttl(_CIRCUIT_OPEN_KEY)
    except Exception as e:
        _mark_redis_unavailable(f"_ensure_probe_armed: {e}")
        return

    if ttl_ms is None or ttl_ms <= 0:
        return  # TTL race — key vanished between GET and PTTL.

    remaining = ttl_ms / 1000.0
    delay = max(0.0, remaining - _PROBE_LEAD_SECONDS)
    _pending_probe = loop.create_task(_probe_at_expiry(delay))


async def record_global_failure() -> None:
    """Track failure timestamp; open circuit when threshold reached in window."""
    global _local_circuit_open_until
    now = time.monotonic()
    threshold = runtime_settings.resolve("CIRCUIT_FAILURE_THRESHOLD")
    window = runtime_settings.resolve("CIRCUIT_FAILURE_WINDOW")
    duration = runtime_settings.resolve("CIRCUIT_OPEN_DURATION")

    client = _get_redis()
    if client is not None:
        try:
            # Sorted set keyed by timestamp; trim out-of-window entries first.
            unix_now = time.time()
            window_start = unix_now - window
            await client.zremrangebyscore(_FAILURES_KEY, 0, window_start)
            await client.zadd(_FAILURES_KEY, {str(unix_now): unix_now})
            await client.expire(_FAILURES_KEY, int(window) + 1)
            count = await client.zcount(_FAILURES_KEY, window_start, "+inf")
            if count >= threshold:
                # SET NX so the open window doesn't restart on every new failure.
                opened = await client.set(_CIRCUIT_OPEN_KEY, "1", ex=int(duration), nx=True)
                logger.error(
                    f"Circuit OPEN — {count} primary failures in last {window:.0f}s. "
                    f"Routing all calls to fallback for {duration:.0f}s."
                )
                if opened:
                    _schedule_probe(duration)
            return
        except Exception as e:
            _mark_redis_unavailable(f"record_global_failure: {e}")

    _local_failures.append(now)
    window_start = now - window
    recent = sum(1 for ts in _local_failures if ts >= window_start)
    if recent >= threshold and time.monotonic() >= _local_circuit_open_until:
        _local_circuit_open_until = now + duration
        logger.error(
            f"Circuit OPEN (in-memory) — {recent} primary failures in last {window:.0f}s. "
            f"Routing all calls to fallback for {duration:.0f}s."
        )
        _schedule_probe(duration)


# ─── Health-probe transitions ────────────────────────────────────────────────
#
# When the circuit opens, ``_schedule_probe`` arms a one-shot async task to
# fire ~PROBE_LEAD_SECONDS before the open window would expire. The probe
# calls ``llm_fallback.probe_primary`` (zero-token GET /v1/models) and:
#
#   primary healthy → ``force_close_circuit`` + ``clear_all_degraded``
#   primary still down → ``force_open_circuit`` to extend the window for
#       another full duration (and re-arms the next probe)
#
# This eliminates the "canary user" pattern where the first N requests
# after TTL-expiry served as live probes, taking the failure hit for
# everyone else.


async def clear_all_degraded() -> int:
    """Clear all per-thread degradation marks. Returns count cleared.

    Called by the probe on recovery so existing conversations route back
    to primary on their next turn instead of waiting out
    ``DEGRADED_THREAD_TTL``.
    """
    cleared = 0
    client = _get_redis()
    if client is not None:
        try:
            cursor = 0
            while True:
                cursor, keys = await client.scan(
                    cursor=cursor, match=_THREAD_PREFIX + "*", count=500
                )
                if keys:
                    cleared += await client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            _mark_redis_unavailable(f"clear_all_degraded: {e}")
    cleared += len(_local_degraded)
    _local_degraded.clear()
    return cleared


async def force_close_circuit() -> None:
    """Close the global circuit immediately and drop the failure history.

    Called by the probe when the primary recovers before the open window
    would naturally expire.
    """
    global _local_circuit_open_until
    client = _get_redis()
    if client is not None:
        try:
            await client.delete(_CIRCUIT_OPEN_KEY)
            await client.delete(_FAILURES_KEY)
        except Exception as e:
            _mark_redis_unavailable(f"force_close_circuit: {e}")
    _local_circuit_open_until = 0.0
    _local_failures.clear()


async def force_open_circuit(duration: float) -> None:
    """(Re)open the circuit for ``duration`` seconds and arm a new probe.

    Called by the probe when the primary is still unhealthy at the
    boundary of an open window — extends the fallback period rather
    than letting Redis TTL flip traffic back to a broken primary.
    """
    global _local_circuit_open_until
    client = _get_redis()
    if client is not None:
        try:
            await client.set(_CIRCUIT_OPEN_KEY, "1", ex=int(duration))
        except Exception as e:
            _mark_redis_unavailable(f"force_open_circuit: {e}")
    _local_circuit_open_until = time.monotonic() + duration
    _schedule_probe(duration)


def _schedule_probe(duration: float) -> None:
    """Arm a one-shot probe to fire ~PROBE_LEAD_SECONDS before the TTL expires.

    Cancels any previously-pending probe so an updated duration takes
    precedence (e.g. ``force_open_circuit`` while a probe was pending).
    No-op when ``HEALTH_PROBE_ENABLED`` is False or no event loop is
    running (tests with sync setup, etc.).
    """
    global _pending_probe
    if not runtime_settings.resolve("HEALTH_PROBE_ENABLED"):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop — caller is sync; probe machinery doesn't apply

    if _pending_probe is not None and not _pending_probe.done():
        _pending_probe.cancel()

    delay = max(0.0, duration - _PROBE_LEAD_SECONDS)
    _pending_probe = loop.create_task(_probe_at_expiry(delay))


async def _probe_at_expiry(delay: float) -> None:
    """Sleep ``delay``, then probe primary and decide extend vs release.

    Cross-worker dedup: only one pod actually runs the probe per open
    cycle (Redis SETNX lock with TTL = 60s).
    """
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    client = _get_redis()
    if client is not None:
        try:
            got_lock = await client.set(_PROBE_LOCK_KEY, "1", ex=60, nx=True)
            if not got_lock:
                return
        except Exception as e:
            _mark_redis_unavailable(f"probe_lock: {e}")
            # Lock unavailable → still probe locally; worst case is a
            # duplicate call. Better than skipping recovery.

    # Local import to avoid circular dependency at module-load time.
    from agents.bo_facil.core import llm_fallback

    ok = await llm_fallback.probe_primary()

    if ok:
        logger.info("Health probe: primary recovered — closing circuit")
        await force_close_circuit()
        await clear_all_degraded()
    else:
        new_duration = runtime_settings.resolve("CIRCUIT_OPEN_DURATION")
        logger.warning(
            "Health probe: primary still down — extending circuit for %.0fs", new_duration
        )
        await force_open_circuit(new_duration)


# ─── Admin helpers ───────────────────────────────────────────────────────────


async def get_circuit_snapshot() -> dict:
    """Read-only view of circuit state for /admin/circuit-state.

    Fields:
      circuit_open: bool — true when the circuit is currently open
      circuit_open_ttl_seconds: int | None — Redis remaining TTL, None when
        Redis is unavailable / circuit is closed / running in-memory mode
      failures_in_window: int — failures counted in the current sliding window
      degraded_threads_count: int — number of thread:degraded keys live now
      pending_probe_local: bool — true when *this* worker has a probe task
        armed and not yet resolved. Cross-worker count is not knowable here.
    """
    snapshot: dict = {
        "circuit_open": False,
        "circuit_open_ttl_seconds": None,
        "failures_in_window": 0,
        "degraded_threads_count": 0,
        "pending_probe_local": (_pending_probe is not None and not _pending_probe.done()),
    }

    client = _get_redis()
    if client is not None:
        try:
            value = await client.get(_CIRCUIT_OPEN_KEY)
            snapshot["circuit_open"] = value is not None
            if snapshot["circuit_open"]:
                ttl = await client.ttl(_CIRCUIT_OPEN_KEY)
                snapshot["circuit_open_ttl_seconds"] = ttl if ttl > 0 else None
            window = runtime_settings.resolve("CIRCUIT_FAILURE_WINDOW")
            now = time.time()
            snapshot["failures_in_window"] = int(
                await client.zcount(_FAILURES_KEY, now - window, "+inf")
            )
            cursor = 0
            count = 0
            while True:
                cursor, keys = await client.scan(
                    cursor=cursor, match=_THREAD_PREFIX + "*", count=500
                )
                count += len(keys)
                if cursor == 0:
                    break
            snapshot["degraded_threads_count"] = count
            return snapshot
        except Exception as e:
            _mark_redis_unavailable(f"get_circuit_snapshot: {e}")

    # In-memory fallback
    now = time.monotonic()
    snapshot["circuit_open"] = now < _local_circuit_open_until
    window = runtime_settings.resolve("CIRCUIT_FAILURE_WINDOW")
    snapshot["failures_in_window"] = sum(1 for ts in _local_failures if ts >= now - window)
    snapshot["degraded_threads_count"] = len(_local_degraded)
    return snapshot


async def clear_circuit_state() -> bool:
    """Wipe circuit-breaker state: Redis keys + in-memory open window + history.

    Intended as an operator escape hatch when the cluster gets stuck and
    the operator wants to force a clean state without waiting for TTL.
    Idempotent: a no-op DELETE on already-clean state succeeds.

    Does NOT clear degraded thread marks — those have a short TTL and
    the threads will retry primary on their own.
    """
    global _local_circuit_open_until, _pending_probe

    client = _get_redis()
    if client is not None:
        try:
            await client.delete(_CIRCUIT_OPEN_KEY, _FAILURES_KEY, _PROBE_LOCK_KEY)
        except Exception as e:
            _mark_redis_unavailable(f"clear_circuit_state: {e}")

    _local_circuit_open_until = 0.0
    _local_failures.clear()
    if _pending_probe is not None and not _pending_probe.done():
        _pending_probe.cancel()
    _pending_probe = None
    return True


# ─── Test helpers ────────────────────────────────────────────────────────────


def _reset_local_state() -> None:
    """Reset in-memory state — used by tests."""
    global _local_circuit_open_until, _redis_unavailable_until, _pending_probe
    _local_degraded.clear()
    _local_failures.clear()
    _local_circuit_open_until = 0.0
    _redis_unavailable_until = 0.0
    if _pending_probe is not None and not _pending_probe.done():
        try:
            _pending_probe.cancel()
        except RuntimeError:
            # Loop may already be closed (cross-test teardown). The task
            # ref will be GC'd along with the loop — nothing to do.
            pass
    _pending_probe = None
