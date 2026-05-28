from __future__ import annotations

import datetime

from sqlalchemy.exc import IntegrityError
from loguru import logger as log
from typing import Annotated, Dict, Optional
from pwdlib import PasswordHash
from jwt import decode, encode

from fastapi import HTTPException, status, Depends, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.routing import APIRouter

from app.config import Config
from app.models.database import DatabaseClient, SessionDependency, User
from app.models.requests import CreateUserRequest, Token

auth_router = APIRouter(prefix="/authentication")
password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=auth_router.prefix + "/token")


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
    token = encode(payload, key=Config.SECRET_KEY, algorithm=Config.ALGORITHM)

    return token


async def get_current_user(
    session: SessionDependency, auth: AuthDependency
) -> Optional[User]:
    try:
        payload = decode(auth, key=Config.SECRET_KEY, algorithms=[Config.ALGORITHM])
        return DatabaseClient.fetch_user(session, payload["username"])

    except Exception as exc:
        log.warning("Failed to authenticate user - {} (auth={})", exc, auth)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@auth_router.post("/token")
async def logic(session: SessionDependency, auth_form: AuthFormDependency) -> None:
    exception = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not (
        row := DatabaseClient.fetch_user(session, auth_form.username)
    ) or not verify_password(auth_form.password, row.hashed_password):
        raise exception

    access_token = create_access_token({"username": auth_form.username})

    return Token(access_token=access_token, token_type="bearer")


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    session: SessionDependency, request: Annotated[CreateUserRequest, Form()]
):
    try:
        DatabaseClient.insert_user(session, request)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already taken"
        )


AuthDependency = Annotated[str, Depends(oauth2_scheme)]
AuthFormDependency = Annotated[OAuth2PasswordRequestForm, Depends()]
UserDependency = Annotated[User, Depends(get_current_user)]
