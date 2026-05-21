from typing import Annotated
from fastapi import FastAPI, Path
from fastapi.responses import RedirectResponse
from fastapi.requests import Request
from fastapi.exceptions import HTTPException

from app.config import Config
from app.models.database import DatabaseClient, SessionDep
from app.models.requests import CreateUrlRequest, CreateUrlResponse
from app.utils import format_redirect_url, generate_random_id

app = FastAPI(debug=Config.is_development_environment())


@app.get("/")
async def home():
    return "Hello World!"


@app.get("/u/{url}")
async def get_url(url: Annotated[str, Path], session: SessionDep):
    if row := DatabaseClient.get_url_from_alias(session, url):
        return RedirectResponse(row.origin)

    raise HTTPException(status_code=404, detail="Redirect not found")


@app.post("/create_url")
async def create_url(
    http_request: Request, request: CreateUrlRequest, session: SessionDep
) -> CreateUrlResponse:
    if row := DatabaseClient.get_url_row(session, request.url):
        return CreateUrlResponse(url_path=format_redirect_url(http_request, row.alias))

    alias = generate_random_id()
    DatabaseClient.insert_url(session, request.url, alias)

    return CreateUrlResponse(url_path=format_redirect_url(http_request, alias))
