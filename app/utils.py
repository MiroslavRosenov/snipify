import functools
import inspect
import secrets
import time
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from app.config import Config

T = TypeVar("T")

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Available to every template (e.g. the contact link in the shared footer).
templates.env.globals["contact_email"] = Config.CONTACT_EMAIL

HTTP_ERRORS: dict[int, tuple[str, str]] = {
    400: (
        "Bad Request",
        "The request could not be understood. Please check your input and try again.",
    ),
    401: ("Authentication Required", "You need to sign in to access this page."),
    403: ("Access Denied", "You don't have permission to access this resource."),
    404: (
        "Page Not Found",
        "The page you're looking for doesn't exist or has been moved.",
    ),
    405: ("Method Not Allowed", "This action is not supported here."),
    408: ("Request Timeout", "The request took too long. Please try again."),
    409: ("Conflict", "There was a conflict with the current state of the resource."),
    410: ("Gone", "This page has been permanently removed."),
    422: (
        "Invalid Request",
        "The request could not be processed. Please check your input.",
    ),
    429: (
        "Too Many Requests",
        "You've made too many requests. Please wait a moment before trying again.",
    ),
    500: (
        "Internal Server Error",
        "Something went wrong on our end. Please try again later.",
    ),
    502: (
        "Bad Gateway",
        "The server received an invalid response. Please try again later.",
    ),
    503: (
        "Service Unavailable",
        "The service is temporarily unavailable. Please try again later.",
    ),
    504: (
        "Gateway Timeout",
        "The server didn't respond in time. Please try again later.",
    ),
}

DEFAULT_ERROR = ("Error", "An unexpected error occurred. Please try again later.")


def generate_random_id() -> str:
    return secrets.token_urlsafe(6)


def get_client_ip(request: Request) -> str:
    """Best-effort client IP, honoring the usual reverse-proxy headers.

    The app sits behind a proxy, so ``request.client.host`` is the proxy, not
    the caller. We therefore trust, in order of preference:

    * ``X-Forwarded-For`` — a ``client, proxy1, proxy2`` chain whose left-most
      entry is the original client as seen by the first proxy.
    * ``X-Real-IP`` — a single address some proxies set instead.
    * the direct socket peer (``request.client.host``) as a last resort.

    Falls back to ``"-"`` when none are available (e.g. in tests). These
    headers are client-spoofable, so the result is only as trustworthy as the
    proxy that sets them — fine for rate-limiting/logging, not for authz.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client = forwarded.split(",")[0].strip()
        if client:
            return client

    real_ip = request.headers.get("X-Real-IP")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    return getattr(request.client, "host", "-") or "-"


def format_redirect_url(request: Request, alias: str) -> str:
    return request.base_url._url + alias


def error_response(request: Request, status_code: int) -> HTMLResponse:
    title, description = HTTP_ERRORS.get(status_code, DEFAULT_ERROR)

    return templates.TemplateResponse(
        request,
        "error.html",
        context={
            "request": request,
            "user": None,
            "status_code": status_code,
            "title": title,
            "description": description,
        },
        status_code=status_code,
    )


def friendly_validation_message(errors: list) -> str:
    for e in errors:
        loc = e.get("loc", [])
        field = str(loc[-1]) if loc else ""
        error_type = e.get("type", "")
        if field == "email" or (
            error_type == "value_error" and "email" in e.get("msg", "").lower()
        ):
            return "Please enter a valid email address."
        if field == "url" or error_type.startswith("url_"):
            return "Please enter a valid URL."
    first = errors[0] if errors else {}
    return first.get("msg", "Invalid input. Please check your data.")


def _log_elapsed(name: str, start: float) -> None:
    elapsed_ms = (time.perf_counter() - start) * 1000
    # opt(depth=1) so the log points at the decorated call site, not this module.
    logger.opt(depth=1).debug(
        "Function call for '{}' took {:.2f} ms to complete", name, elapsed_ms
    )


def _timeit_sync(func: Callable[..., T]) -> Callable[..., T]:
    """Log the wall-clock time of a sync function call at DEBUG level."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> T:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            _log_elapsed(func.__qualname__, start)

    return wrapper


def _timeit_async(
    func: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    """Log the wall-clock time of an async function call at DEBUG level."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        start = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            _log_elapsed(func.__qualname__, start)

    return wrapper


def timeit(func: Callable[..., T]) -> Callable[..., T]:
    """
    Time a function call at DEBUG level, picking the right wrapper for

    sync vs. async automatically.
    """
    if inspect.iscoroutinefunction(func):
        return _timeit_async(func)  # type: ignore[return-value]
    return _timeit_sync(func)
