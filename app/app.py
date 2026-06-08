from pathlib import Path
from time import time
from typing import Awaitable, Callable
from loguru import logger as log

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from uvicorn.protocols.utils import get_path_with_query_string

from app.config import Config
from app.api.routers.security import auth_router
from app.api.routers.redirect import redirect_router
from app.api.routers.pages import pages_router
from app.models.database import DatabaseClient
from app.models.redis import RedisClient
from app.smtp_client import SMTPClient
from app.utils import error_response, friendly_validation_message


async def create_dependencies() -> None:
    DatabaseClient.get_instance(Config.DATABASE_URL)
    RedisClient.get_instance(Config.REDIS_URL)
    SMTPClient.get_instance()


async def app_lifespan(app: FastAPI):
    await create_dependencies()
    log.success("Successfully started the app on '{}' environment", Config.ENVIRONMENT)
    yield
    await cleanup_dependecies()


async def cleanup_dependecies() -> None:
    await DatabaseClient.cleanup()
    await RedisClient.cleanup()
    await SMTPClient.cleanup()


is_dev_environment = Config.is_development_environment()
app = FastAPI(
    debug=is_dev_environment,
    lifespan=app_lifespan,
    docs_url="/docs" if is_dev_environment else None,
    redoc_url="/redoc" if is_dev_environment else None,
    openapi_url="/openapi.json" if is_dev_environment else None,
)
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
async def not_found_exception_handler(request: Request, exc: HTTPException):
    return error_response(request, 404)


@app.exception_handler(500)
async def server_exception_handler(request: Request, exc: HTTPException):
    log.opt(exception=exc).error("Unexpected error on request {} - {}", request, exc)
    return error_response(request, 500)


@app.middleware("http")
async def requests_log_middleware(
    http_request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start_time = time()
    response = await call_next(http_request)
    process_time = time() - start_time

    scope = http_request.scope
    log_function = (
        log.info
        if (
            process_time < 2
            and (response.status_code >= 200 and response.status_code < 400)
        )
        else log.warning
    )  # 2xx and 3xx would be successful responses
    log_function(
        "{} request from {} on route '{}' HTTP/{} with status code {} took {} seconds to process",
        scope["method"],
        http_request.headers.get(
            "X-Real-IP", getattr(http_request.client, "host", "-")
        ),
        get_path_with_query_string(scope),
        scope["http_version"],
        response.status_code,
        round(process_time, 2),
    )

    return response
