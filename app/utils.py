import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Config

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
