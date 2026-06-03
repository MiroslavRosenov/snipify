from time import time
from typing import Awaitable, Callable
from loguru import logger as log

from fastapi import FastAPI, Request, Response

from app.config import Config
from app.api.routers.security import auth_router
from app.api.routers.redirect import redirect_router
from app.api.routers.pages import pages_router
from app.models.database import DatabaseClient


async def create_dependencies() -> None:
    DatabaseClient.get_instance(
        Config.DATABASE_URL
    )  # This call would fill the 'instance' cache for next calls


async def app_lifespan(app: FastAPI):
    yield
    await cleanup_dependecies()


async def cleanup_dependecies() -> None:
    await DatabaseClient.cleanup()


app = FastAPI(debug=Config.is_development_environment(), lifespan=app_lifespan)
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(redirect_router)

if Config.is_development_environment():

    @app.middleware("http")
    async def add_process_time_header(
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
