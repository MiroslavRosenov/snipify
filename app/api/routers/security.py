from __future__ import annotations

import datetime
import jwt

from sqlalchemy.exc import IntegrityError
from loguru import logger as log
from typing import Annotated, Optional
from pwdlib import PasswordHash

from fastapi import HTTPException, Request, status, Depends, Form
from fastapi.routing import APIRouter

from app.config import Config
from app.models.database import DatabaseClient, SessionDependency, User
from app.models.requests import UserAuthRequest, Token

auth_router = APIRouter(prefix="/authentication")
password_hash = PasswordHash.recommended()


def verify_password(password: str, hash: str) -> bool:
    return password_hash.verify(password, hash)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def create_access_token(data: dict, expires_delta: datetime.timedelta | None = None):
    payload = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + datetime.timedelta(minutes=15)

    payload.update({"exp": expire, "iat": now})
    token = jwt.encode(payload, key=Config.SECRET_KEY, algorithm=Config.ALGORITHM)

    return token


async def get_authentication_header(request: Request) -> str:
    if not (authentication_header := request.headers.get("Authorization")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return authentication_header.lstrip("Bearer").strip()


async def get_signed_user(
    session: SessionDependency, auth: AuthDependency
) -> Optional[User]:
    try:
        payload = jwt.decode(auth, key=Config.SECRET_KEY, algorithms=[Config.ALGORITHM])
        return await DatabaseClient.fetch_user(session, payload["email"])

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization expired"
        )

    except jwt.InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authorization"
        )

    except Exception as exc:
        log.opt(exception=exc).error(
            "Failed to authenticate user - {} (auth={})", exc, auth
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@auth_router.post("/token")
async def login(session: SessionDependency, request: UserAuthRequest) -> None:
    exception = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not (
        row := await DatabaseClient.fetch_user(session, request.email)
    ) or not verify_password(request.password, row.hashed_password):
        raise exception

    access_token = create_access_token({"email": request.email})

    return Token(access_token=access_token, token_type="bearer")


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(session: SessionDependency, request: UserAuthRequest):
    try:
        await DatabaseClient.insert_user(session, request)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already taken"
        )


AuthDependency = Annotated[str, Depends(get_authentication_header)]
UserDependency = Annotated[User, Depends(get_signed_user)]
