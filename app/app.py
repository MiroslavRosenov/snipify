from typing import Annotated
from fastapi import FastAPI, Path

from app.models.requests import CreateUrlRequest, CreateUrlResponse

app = FastAPI(debug=True)


@app.get("/")
async def home():
    return "Hello World!"


@app.get("/{url}")
async def get_url(url: Annotated[str, Path]):
    return {"params": {"url": url}}


@app.post("/create_url")
async def create_url(request: CreateUrlRequest) -> CreateUrlResponse: ...
