from fastapi import FastAPI

from app.config import Config
from app.api.routers.security import auth_router
from app.api.routers.redirect import redirect_router

app = FastAPI(debug=Config.is_development_environment())
app.include_router(auth_router)
app.include_router(redirect_router)


@app.get("/")
async def home():
    return "Hello World!"
