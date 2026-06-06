from typing import Annotated

from fastapi import status, HTTPException, Path, Query
from fastapi.routing import APIRouter

from fastapi.responses import RedirectResponse
from fastapi.requests import Request

from app.api.routers.security import UserDependency
from app.models.database import SessionDependency, Url
from app.models.requests import (
    CreateUrlRequest,
    CreateUrlResponse,
    PaginatedUrlsResponse,
    UrlItemResponse,
)
from app.utils import format_redirect_url, generate_random_id

redirect_router = APIRouter()


@redirect_router.get("/urls")
async def get_user_urls(
    http_request: Request,
    user: UserDependency,
    session: SessionDependency,
    page: int = Query(1, ge=1),
) -> PaginatedUrlsResponse:
    limit = 10
    offset = (page - 1) * limit
    total = await Url.count_by_user_id(session, user.id)
    urls = await Url.get_by_user_id(session, user.id, offset=offset, limit=limit)
    pages = max(1, (total + limit - 1) // limit)
    return PaginatedUrlsResponse(
        items=[
            UrlItemResponse(
                origin=url.origin,
                alias=url.alias,
                short_url=format_redirect_url(http_request, url.alias),
            )
            for url in urls
        ],
        total=total,
        page=page,
        pages=pages,
    )


@redirect_router.post("/create_url")
async def create_url(
    http_request: Request,
    request: CreateUrlRequest,
    session: SessionDependency,
    user: UserDependency,
) -> CreateUrlResponse:
    url = str(request.url._url)
    if row := await Url.get_url_row(session, url):
        return CreateUrlResponse(url_path=format_redirect_url(http_request, row.alias))

    alias = generate_random_id()
    await Url.insert(session, url, alias, user.id)

    return CreateUrlResponse(url_path=format_redirect_url(http_request, alias))


@redirect_router.get("/{url}")
async def get_url(
    url: Annotated[str, Path()], request: Request, session: SessionDependency
):
    if row := await Url.get_url_from_alias(session, url):
        return RedirectResponse(row.origin)

    raise HTTPException(status.HTTP_404_NOT_FOUND)
