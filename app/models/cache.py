"""Caching primitives used across the app.

Two independent layers live here:

* **In-memory LRU** (`LRUCache` + the `cached` / `invalidates` decorators) —
  a process-local cache with zero network cost, used for the auth hot path
  (``User.get_by_email``). Because it lives inside a single worker process it
  is the fastest option available, but it is *not* shared between workers:
  every worker keeps its own copy, so an invalidation in one worker does not
  reach the others. Safe for single- (or few-) worker deployments.

* **Redis-backed listing cache** (`read_cache` / `write_cache` /
  `invalidate_user_urls`) — a cross-process cache for paginated URL listings.
  Every helper degrades gracefully: if Redis is unreachable the call is logged
  and treated as a miss/no-op so the request still succeeds against the DB.
"""

import functools
import inspect
import json

from collections import OrderedDict
from typing import Awaitable, Callable, Generic, Optional, TypeVar, Union

from loguru import logger as log

from redis.asyncio import Redis

from app.utils import timeit

K = TypeVar("K")  # cache key type
V = TypeVar("V")  # cached value type


# ── In-memory LRU cache ──────────────────────────────────────────────────────


class LRUCache(Generic[K, V]):
    """A tiny, process-local least-recently-used cache.

    Backed by an ``OrderedDict`` where iteration order tracks recency: the
    most-recently-used key sits at the end, the least-recently-used at the
    front. When the cache grows past ``maxsize`` the front entry is evicted.
    This keeps memory bounded while retaining the hottest keys.

    It is deliberately minimal — no TTL, no thread locks, no serialization —
    because it is meant for single-process use on the asyncio event loop, where
    access is never truly concurrent. For cross-process caching use the
    Redis-backed helpers below instead.

    Type parameters:
        K: the key type (e.g. ``str`` for an email).
        V: the stored value type (e.g. a detached ORM row).
    """

    def __init__(self, maxsize: int = 512) -> None:
        """Create an empty cache holding at most ``maxsize`` entries."""
        self._maxsize = maxsize
        self._store: "OrderedDict[K, V]" = OrderedDict()

    def get(self, key: K) -> Optional[V]:
        """Return the value for ``key``, or ``None`` if absent.

        On a hit the key is promoted to most-recently-used so it survives
        eviction longer. ``None`` is also what a genuine ``None`` value would
        return, so this cache should only store non-``None`` values (which is
        what `cached` guarantees).
        """
        if key not in self._store:
            return None
        self._store.move_to_end(key)  # mark as most-recently used
        return self._store[key]

    def set(self, key: K, value: V) -> None:
        """Insert/update ``key`` as most-recently-used, evicting if over size.

        If adding this entry pushes the cache past ``maxsize``, the single
        least-recently-used entry (the front of the ordering) is dropped.
        """
        self._store[key] = value
        self._store.move_to_end(key)
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)  # evict least-recently used

    def pop(self, key: K) -> None:
        """Remove ``key`` if present; a no-op when it is not (used to invalidate)."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Drop every entry — mainly useful in tests and between runs."""
        self._store.clear()


def cached(
    cache: LRUCache,
    key: Callable[..., K],
    store: Optional[Callable[..., V]] = None,
) -> Callable:
    """Decorator that memoizes an async function's result in an `LRUCache`.

    On each call the wrapped function's arguments are passed to ``key`` to
    compute a cache key. A hit returns the cached value without running the
    function; a miss runs it, stores a non-``None`` result, and returns it.

    Args:
        cache: the `LRUCache` instance to read from and write to. Pass the same
            instance to the matching `invalidates` decorators so reads and
            evictions target one cache.
        key: maps the wrapped function's ``(*args, **kwargs)`` to a cache key.
            It must be cheap and side-effect free, e.g.
            ``lambda session, email: email``.
        store: optional transform applied to the result *before* caching. Use it
            when the raw result is unsafe to retain — e.g.
            ``lambda user: user.snapshot()`` to keep a session-detached copy of
            an ORM row instead of the live (soon-to-be-expired) instance.

    Notes:
        ``None`` results are never cached, so lookups that miss in the DB keep
        hitting it rather than caching a negative result. Stack this *below*
        ``@staticmethod`` / ``@timeit`` so those wrap the cache-aware callable.

    Example:
        >>> @cached(cache=user_email_cache,
        ...         key=lambda session, email: email,
        ...         store=lambda user: user.snapshot())
        ... async def get_by_email(session, email): ...
    """

    def decorator(func: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = key(*args, **kwargs)

            hit = cache.get(cache_key)
            if hit is not None:
                return hit

            result = await func(*args, **kwargs)
            if result is not None:
                cache.set(cache_key, store(result) if store else result)
            return result

        return wrapper

    return decorator


def invalidates(
    cache: LRUCache,
    key: Callable[..., Union[K, Awaitable[K]]],
) -> Callable:
    """Decorator that evicts a cache entry after a mutating async function runs.

    The wrapped function runs first; only then is its key computed and removed.
    Ordering matters: by running the mutation first, a ``key`` resolver that has
    to query the database (see below) observes the just-written state.

    Args:
        cache: the `LRUCache` to evict from — the same instance the matching
            `cached` decorator reads from.
        key: maps the wrapped function's ``(*args, **kwargs)`` to the key to
            drop. It may return the key directly
            (``lambda session, email, pw: email``) **or** an awaitable that
            resolves to it (``lambda session, user_id, pw:
            email_for_id(session, user_id)``) for when the cache is keyed by a
            value the mutator does not receive directly. A ``None`` result skips
            eviction.

    Notes:
        Eviction is local to this process. With multiple workers, sibling
        workers keep their stale copy until it ages out — see the module
        docstring. Attach one `invalidates` per field-changing method so the
        cache cannot outlive a write to a cached column.

    Example:
        >>> @invalidates(cache=user_email_cache,
        ...              key=lambda session, user_id, pw:
        ...                  email_for_id(session, user_id))
        ... async def update_password_by_id(session, user_id, pw): ...
    """

    def decorator(func: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            cache_key = key(*args, **kwargs)
            if inspect.isawaitable(cache_key):
                cache_key = await cache_key
            if cache_key is not None:
                cache.pop(cache_key)

            return result

        return wrapper

    return decorator


# ── Redis-backed listing cache ───────────────────────────────────────────────

# Cached listings are also expired by this TTL as a safety net in case an
# invalidation is ever missed.
URLS_CACHE_TTL = 300


def urls_cache_key(user_id: int, page: int) -> str:
    """Build the Redis key for one page of a user's listing.

    The ``user_urls:{user_id}:{page}`` shape gives every page its own entry
    while sharing the ``user_urls:{user_id}:*`` prefix, which is what
    `invalidate_user_urls` scans to clear *all* of a user's pages at once.
    """
    return f"user_urls:{user_id}:{page}"


@timeit
async def read_cache(redis: Redis, key: str) -> dict | None:
    """Read and JSON-decode a cached payload.

    Args:
        redis: the async Redis client.
        key: the key to read, e.g. from `urls_cache_key`.

    Returns:
        The decoded ``dict`` on a hit, or ``None`` on a miss **or** if Redis is
        unreachable. Treating an outage as a miss lets the caller fall back to
        the database so a Redis failure degrades performance, not correctness.
    """
    try:
        cached = await redis.get(key)
    except Exception as exc:
        log.opt(exception=exc).warning("Redis read failed for '{}' - {}", key, exc)
        return None
    return json.loads(cached) if cached is not None else None


@timeit
async def write_cache(
    redis: Redis, key: str, data: dict, ttl: int = URLS_CACHE_TTL
) -> None:
    """JSON-encode and store ``data`` under ``key`` with an expiry.

    Args:
        redis: the async Redis client.
        key: the key to write, e.g. from `urls_cache_key`.
        data: a JSON-serializable payload (the listing page).
        ttl: expiry in seconds; defaults to `URLS_CACHE_TTL` as a safety net so
            a missed invalidation cannot leave data stale forever.

    A Redis failure is logged and swallowed: failing to populate the cache must
    never break the request that produced the data.
    """
    try:
        await redis.set(key, json.dumps(data), ex=ttl)
    except Exception as exc:
        log.opt(exception=exc).warning("Redis write failed for '{}' - {}", key, exc)


@timeit
async def invalidate_user_urls(redis: Redis, user_id: int) -> None:
    """Evict every cached listing page for a user.

    A single new/changed URL can shift items across *all* pages, so partial
    invalidation is not enough — this scans the ``user_urls:{user_id}:*``
    prefix and deletes whatever it finds. ``scan_iter`` is used instead of
    ``KEYS`` so it does not block Redis on large keyspaces.

    Like the other helpers, any Redis error is logged and ignored; the worst
    case is that callers serve slightly stale pages until the TTL expires.
    """
    try:
        keys = [key async for key in redis.scan_iter(match=f"user_urls:{user_id}:*")]
        if keys:
            await redis.delete(*keys)
    except Exception as exc:
        log.opt(exception=exc).warning(
            "Redis invalidation failed for user {} - {}", user_id, exc
        )
