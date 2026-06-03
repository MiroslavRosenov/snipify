from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRouter
from fastapi.templating import Jinja2Templates

from app.api.routers.security import get_signed_user
from app.models.database import SessionDependency, User

pages_router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent.parent / "templates")


async def get_optional_user(
    session: SessionDependency,
    http_request: Request,
    http_response: Response,
) -> Optional[User]:
    try:
        return await get_signed_user(session, http_request, http_response)
    except Exception:
        return None


OptionalUserDependency = Annotated[Optional[User], Depends(get_optional_user)]


@pages_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: OptionalUserDependency):
    return templates.TemplateResponse(
        request, "index.html", {"request": request, "user": user}
    )


@pages_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: OptionalUserDependency):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"request": request, "user": None}
    )


@pages_router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user: OptionalUserDependency):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request, "register.html", {"request": request, "user": None}
    )
