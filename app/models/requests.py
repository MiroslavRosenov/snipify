from pydantic import BaseModel, HttpUrl, EmailStr


class CreateUrlRequest(BaseModel):
    url: HttpUrl


class CreateUrlResponse(BaseModel):
    url_path: str


class UrlItemResponse(BaseModel):
    origin: str
    alias: str
    short_url: str


class PaginatedUrlsResponse(BaseModel):
    items: list[UrlItemResponse]
    total: int
    page: int
    pages: int


class UserAuthRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str
