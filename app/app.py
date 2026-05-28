from fastapi import FastAPI

from app.config import Config
from app.api.routers.security import auth_router
from app.api.routers.redirect import redirect_router
from app.models.database import DatabaseClient


async def create_dependencies() -> None:
    DatabaseClient.get_instance(
        Config.DATABASE_URL
    )  # This call would fill the 'instance' cache for next calls


async def app_lifespan(app: FastAPI):
    await create_dependencies()
    yield
    await cleanup_dependecies()


async def cleanup_dependecies() -> None:
    await DatabaseClient.cleanup()


app = FastAPI(debug=Config.is_development_environment(), lifespan=app_lifespan)
app.include_router(auth_router)
app.include_router(redirect_router)


@app.get("/")
async def home():
    return "Hello World!"
