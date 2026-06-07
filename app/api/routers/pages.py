from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRouter
from fastapi.templating import Jinja2Templates
from loguru import logger as log

from app.api.routers.security import decode_jwt_token, get_current_user, hash_value
from app.config import Config
from app.models.database import (
    OneTimeToken,
    OneTimeTokenPurpose,
    SessionDependency,
    User,
)
from app.utils import error_response

pages_router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent.parent / "templates")

# Available to every template (e.g. the contact link in the shared footer).
templates.env.globals["contact_email"] = Config.CONTACT_EMAIL

# Shared values rendered into the legal pages, sourced from configuration.
LEGAL_CONTEXT = {
    "effective_date": Config.LEGAL_EFFECTIVE_DATE,
    "contact_email": Config.CONTACT_EMAIL,
    "governing_law": Config.LEGAL_GOVERNING_LAW,
}


async def get_optional_user(
    session: SessionDependency,
    http_request: Request,
    http_response: Response,
) -> Optional[User]:
    try:
        return await get_current_user(session, http_request, http_response)
    except Exception:
        return None


OptionalUserDependency = Annotated[Optional[User], Depends(get_optional_user)]


def render_legal(
    request: Request, response: Response, user: Optional[User], template: str
) -> HTMLResponse:
    try:
        return templates.TemplateResponse(
            request,
            template,
            context={"request": request, "user": user, **LEGAL_CONTEXT},
            headers=response.headers,
        )
    except Exception:
        return error_response(request, 500)


@pages_router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    return render_legal(request, response, user, "legal/privacy_policy.html")


@pages_router.get("/cookie-policy", response_class=HTMLResponse)
async def cookie_policy_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    return render_legal(request, response, user, "legal/cookie_policy.html")


@pages_router.get("/terms", response_class=HTMLResponse)
async def terms_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    return render_legal(request, response, user, "legal/terms.html")


@pages_router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    try:
        return templates.TemplateResponse(
            request,
            "index.html",
            context={"request": request, "user": user},
            headers=response.headers,
        )
    except Exception:
        return error_response(request, 500)


@pages_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    if not user:
        return RedirectResponse("/login", status_code=302, headers=response.headers)

    try:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            context={"request": request, "user": user},
            headers=response.headers,
        )
    except Exception:
        return error_response(request, 500)


@pages_router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    if user:
        return RedirectResponse("/", status_code=302, headers=response.headers)

    try:
        return templates.TemplateResponse(
            request, "login.html", context={"request": request, "user": None}
        )
    except Exception:
        return error_response(request, 500)


@pages_router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    if user:
        return RedirectResponse("/", status_code=302, headers=response.headers)

    try:
        return templates.TemplateResponse(
            request,
            "register.html",
            context={"request": request, "user": None},
            headers=response.headers,
        )
    except Exception:
        return error_response(request, 500)


@pages_router.get("/activate", response_class=HTMLResponse)
async def activate_page(
    request: Request,
    response: Response,
    session: SessionDependency,
    token: Optional[str] = None,
) -> HTMLResponse:
    def activation_error(title: str, description: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "error.html",
            context={
                "request": request,
                "status_code": "",
                "title": title,
                "description": description,
            },
            status_code=400,
        )

    if not token:
        return activation_error(
            "Invalid activation link", "No activation token was provided."
        )

    payload = decode_jwt_token(token=token, raise_exceptions=False)
    if payload is None:
        log.warning("Account activation attempt with invalid or expired token")
        return activation_error(
            "Activation link expired",
            "This activation link has expired or is invalid. Please register again.",
        )

    stored = await OneTimeToken.get_by_hash(session, hash_value(token))
    if stored is None or stored.used:
        log.warning(
            "Account activation attempt with already used token for ({})",
            payload["sub"],
        )
        return activation_error(
            "Link already used",
            "This activation link has already been used. If your account is active you can log in.",
        )

    user = await User.get_by_email(session, payload["sub"])
    if user is None:
        log.warning(
            "Account activation attempt for non-existing user ({})", payload["sub"]
        )
        return activation_error(
            "Account not found",
            "No account was found for this activation link.",
        )

    await OneTimeToken.invalidate_all_for_user(
        session, user.id, OneTimeTokenPurpose.account_activation
    )
    await User.activate_by_id(session, user.id)

    log.success("Activated account for user ({})", user.email)

    return RedirectResponse(
        "/login?activated=1", status_code=302, headers=response.headers
    )


@pages_router.get("/password-reset", response_class=HTMLResponse)
async def password_reset_page(
    request: Request, response: Response, user: OptionalUserDependency
) -> HTMLResponse:
    if user:
        return RedirectResponse("/", status_code=302, headers=response.headers)

    try:
        return templates.TemplateResponse(
            request,
            "password_reset.html",
            context={"request": request, "user": None},
            headers=response.headers,
        )
    except Exception:
        return error_response(request, 500)


@pages_router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    response: Response,
    user: OptionalUserDependency,
    token: Optional[str] = None,
) -> HTMLResponse:
    if user:
        return RedirectResponse("/", status_code=302, headers=response.headers)

    is_valid_token = decode_jwt_token(token=token, raise_exceptions=False) is not None

    try:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            context={
                "request": request,
                "user": None,
                "is_valid_token": is_valid_token,
                "token": token if is_valid_token else None,
            },
            headers=response.headers,
        )
    except Exception:
        return error_response(request, 500)
