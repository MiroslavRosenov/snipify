"""Redis-backed request rate limiting.

`RATE_LIMITS` is a path-template -> rule map listing exactly which routes are
rate limited; a request to any route absent from the map is never throttled.
For each limited route a fixed-window counter is kept in Redis per *identity*:
the authenticated ``User.id`` when a valid access token is present, otherwise
the caller's IP address. Every route gets its own bucket, so a user spending
their ``/create_url`` budget does not affect their redirect budget.

Like the listing cache (`app.models.cache`), this degrades gracefully: if
Redis is unreachable the request is allowed through rather than failing the
whole app on a dependency that exists to protect it.
"""

from typing import Optional

from loguru import logger as log

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.api.routers.security import decode_jwt_token
from app.models.database import SessionDependency, User
from app.models.redis import RedisDependency
from app.utils import get_client_ip


class RateLimitRule:
    """A request budget: ``max_requests`` allowed per rolling ``window_seconds``."""

    __slots__ = ("max_requests", "window_seconds")

    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds


# Path template (as on the route, e.g. ``/{url}``) -> rule. This map is the
# single source of truth for what is throttled: add an entry to limit a route,
# remove it to stop. Routes not listed here are not rate limited at all.
RATE_LIMITS: dict[str, RateLimitRule] = {
    # Authentication surface — tight budgets to blunt brute-force guessing and
    # email-bombing via the password-reset / activation mailers.
    "/authentication/login": RateLimitRule(10),
    "/authentication/register": RateLimitRule(5),
    "/authentication/password-reset": RateLimitRule(5),
    "/authentication/reset-password": RateLimitRule(10),
    "/authentication/change-password": RateLimitRule(10),
    "/authentication/deactivate-account": RateLimitRule(5),
    # Core write / DB-backed product actions.
    "/create_url": RateLimitRule(30),
    "/urls": RateLimitRule(30),
    # Public redirect resolution — the hot path, kept deliberately generous.
    "/{url}": RateLimitRule(300),
}

# Atomic fixed-window counter. INCR the key and, only on the first hit of a new
# window, stamp it with the TTL; returning the TTL in the same call lets us emit
# an accurate Retry-After without a second round trip. Keeping the INCR/EXPIRE
# pair in Lua means concurrent requests cannot interleave between them and leak
# a key that never expires.
HIT_SCRIPT = (
    "\nlocal current = redis.call('INCR', KEYS[1])"
    "\nif current == 1 then"
    "\nredis.call('EXPIRE', KEYS[1], ARGV[1])"
    "\nend"
    "\nreturn {current, redis.call('TTL', KEYS[1])}"
)


def get_rule_for_route(http_request: Request) -> Optional[tuple[str, RateLimitRule]]:
    """Return ``(path_template, rule)`` for the matched route, or ``None``.

    ``scope["route"]`` is the matched `APIRoute`; its ``path`` is the template
    (``/{url}``), so dynamic routes resolve to one stable config key rather than
    a distinct key per alias.
    """
    route = http_request.scope.get("route")
    template = getattr(route, "path", None)
    if template is None:
        return None
    rule = RATE_LIMITS.get(template)
    return (template, rule) if rule is not None else None


async def get_identity(http_request: Request, session) -> str:
    """Resolve the rate-limit identity for a request.

    Returns ``user:{id}`` when the access-token cookie decodes to a known user
    (resolved through the cached `User.get_by_email`, so it is effectively free
    on the hot path), otherwise ``ip:{address}``.
    """
    access_token = http_request.cookies.get("access_token")
    if access_token:
        payload = decode_jwt_token(token=access_token, raise_exceptions=False)
        if payload and (email := payload.get("sub")):
            user: Optional[User] = await User.get_by_email(session, email)
            if user is not None:
                return f"user:{user.id}"

    return f"ip:{get_client_ip(http_request)}"


async def hit(redis: Redis, key: str, rule: RateLimitRule) -> tuple[int, int]:
    """Increment the window counter, returning ``(count, ttl_seconds)``."""
    count, ttl = await redis.eval(HIT_SCRIPT, 1, key, rule.window_seconds)
    return int(count), int(ttl)


async def enforce_rate_limit(
    http_request: Request,
    session: SessionDependency,
    redis: RedisDependency,
) -> None:
    """FastAPI dependency that throttles the routes listed in `RATE_LIMITS`.

    Routes absent from the map pass straight through. For limited routes it
    raises ``429`` with a ``Retry-After`` header once an identity exceeds the
    rule. Any Redis error is logged and the request is allowed (fail-open).
    """
    matched = get_rule_for_route(http_request)
    if matched is None:
        return

    template, rule = matched
    identity = await get_identity(http_request, session)
    key = f"ratelimit:{template}:{identity}"

    try:
        count, ttl = await hit(redis, key, rule)
    except Exception as exc:
        log.opt(exception=exc).warning(
            "Rate limit check failed for '{}', allowing request - {}", key, exc
        )
        return

    if count > rule.max_requests:
        retry_after = ttl if ttl > 0 else rule.window_seconds
        log.warning(
            "Rate limit exceeded for '{}' on '{}' ({}/{} per {}s)",
            identity,
            template,
            count,
            rule.max_requests,
            rule.window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )
