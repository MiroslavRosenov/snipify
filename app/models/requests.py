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
    refresh_token: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str
