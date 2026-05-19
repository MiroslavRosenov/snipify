from typing import Annotated
from fastapi import FastAPI, Path

app = FastAPI(debug=True)


@app.get("/")
async def home():
    return "Hello World!"


@app.get("/{url}")
async def get_url(url: Annotated[str, Path]):
    return {"params": {"url": url}}
