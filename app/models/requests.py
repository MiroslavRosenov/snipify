from typing import Optional

from pydantic import BaseModel, HttpUrl


class CreateUrlRequest(BaseModel):
    url: HttpUrl


class CreateUrlResponse(BaseModel):
    url_path: str


class UserAuthRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
