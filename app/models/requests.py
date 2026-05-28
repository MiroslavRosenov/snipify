from typing import Optional

from pydantic import BaseModel, Field


class CreateUrlRequest(BaseModel):
    url: str = Field()
    user_id: int


class CreateUrlResponse(BaseModel):
    url_path: str


class CreateUserRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
