from pathlib import Path
from time import time
from typing import Awaitable, Callable
from loguru import logger as log

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Config
from app.api.routers.security import auth_router
from app.api.routers.redirect import redirect_router
from app.api.routers.pages import pages_router
from app.models.database import DatabaseClient
from app.smtp_client import SMTPClient
from app.utils import error_response, friendly_validation_message


async def create_dependencies() -> None:
    DatabaseClient.get_instance(Config.DATABASE_URL)
    SMTPClient.get_instance()


async def app_lifespan(app: FastAPI):
    await create_dependencies()
    yield
    await cleanup_dependecies()


async def cleanup_dependecies() -> None:
    await DatabaseClient.cleanup()
    await SMTPClient.cleanup()


app = FastAPI(debug=Config.is_development_environment(), lifespan=app_lifespan)
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(redirect_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422, content={"detail": friendly_validation_message(exc.errors())}
    )


@app.exception_handler(404)
async def unicorn_exception_handler(request: Request, exc: HTTPException):
    return error_response(request, 404)


if Config.is_development_environment():

    @app.middleware("http")
    async def log_process_time(
        http_request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start_time = time()
        response = await call_next(http_request)
        process_time = time() - start_time

        log_function = log.info if process_time < 2 else log.warning
        log_function(
            "Request from {} took {} seconds to process",
            http_request.url._url,
            round(process_time, 2),
        )

        return response
