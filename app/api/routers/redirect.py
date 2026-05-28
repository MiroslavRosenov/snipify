from typing import Annotated

from fastapi import Path
from fastapi.routing import APIRouter

from fastapi.responses import RedirectResponse
from fastapi.requests import Request
from fastapi.exceptions import HTTPException

from app.api.routers.security import UserDependency
from app.models.database import DatabaseClient, SessionDependency
from app.models.requests import CreateUrlRequest, CreateUrlResponse
from app.utils import format_redirect_url, generate_random_id

redirect_router = APIRouter()


@redirect_router.get("/u/{url}")
async def get_url(url: Annotated[str, Path()], session: SessionDependency):
    if row := await DatabaseClient.get_url_from_alias(session, url):
        return RedirectResponse(row.origin)

    raise HTTPException(status_code=404, detail="Redirect not found")


@redirect_router.post("/create_url")
async def create_url(
    http_request: Request,
    request: CreateUrlRequest,
    session: SessionDependency,
    user: UserDependency,
) -> CreateUrlResponse:
    url = str(request.url._url)
    if row := await DatabaseClient.get_url_row(session, url):
        return CreateUrlResponse(url_path=format_redirect_url(http_request, row.alias))

    alias = generate_random_id()
    await DatabaseClient.insert_url(session, url, alias, user.id)

    return CreateUrlResponse(url_path=format_redirect_url(http_request, alias))
