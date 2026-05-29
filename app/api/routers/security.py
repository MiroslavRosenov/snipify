from __future__ import annotations

import datetime
import secrets
import jwt

from pwdlib.exceptions import UnknownHashError
from sqlalchemy.exc import IntegrityError
from loguru import logger as log
from typing import Annotated, Dict, Optional
from pwdlib import PasswordHash

from fastapi import HTTPException, Request, status, Depends
from fastapi.routing import APIRouter

from app.config import Config
from app.models.database import DatabaseClient, RefreshToken, SessionDependency, User
from app.models.requests import RefreshTokenRequest, UserAuthRequest, Token

auth_router = APIRouter(prefix="/authentication")
password_hash = PasswordHash.recommended()


def verify_hash(value: str, hashed_value: str) -> bool:
    try:
        return password_hash.verify(value, hashed_value)
    except UnknownHashError as exc:
        log.opt(exception=exc).error(
            "Failed to verify hash ('{}' with '{}') - {}", value, hashed_value, exc
        )
        return False


def hash_value(value: str) -> str:
    return password_hash.hash(value)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def encode_jwt_token(*, payload: dict, lifespan: Optional[datetime.timedelta]):
    payload = payload.copy()

    now = datetime.datetime.now(datetime.timezone.utc)
    payload.update({"iat": now})

    if lifespan:
        expire = now + lifespan
        payload.update({"exp": expire})

    token = jwt.encode(payload, key=Config.SECRET_KEY, algorithm=Config.ALGORITHM)

    return token


def decode_jwt_token(token: str) -> Optional[Dict]:
    try:
        payload = jwt.decode(
            token, key=Config.SECRET_KEY, algorithms=[Config.ALGORITHM]
        )
        return payload

    except jwt.ExpiredSignatureError as exc:
        log.warning("Failed to decode JWT token ({}) - authorization expired", token)
        raise exc

    except jwt.InvalidSignatureError:
        log.warning("Failed to decode JWT token ({}) - invalid signature", token)
        raise exc

    except Exception as exc:
        log.opt(exception=exc).error(
            "Failed to decode JWT token ({}) - {}", token, str(exc)
        )
        raise exc


async def get_authentication_header(request: Request) -> str:
    if not (authentication_header := request.headers.get("Authorization")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return authentication_header.lstrip("Bearer").strip()


async def get_signed_user(
    session: SessionDependency, auth_header: AuthDependency
) -> Optional[User]:
    try:
        payload = decode_jwt_token(auth_header)
        return await User.fetch_user(session, payload["email"])

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization expired"
        )

    except jwt.InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authorization"
        )

    except Exception as exc:
        log.opt(exception=exc).error("Failed to authenticate user - {}", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@auth_router.post("/token")
async def create_token(session: SessionDependency, request: UserAuthRequest) -> None:
    if not (user := await User.fetch_user(session, request.email)) or not verify_hash(
        request.password, user.hashed_password
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "The user account is not active"
        )

    if await RefreshToken.is_owner_at_limit(session, user.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Active sessions limit reached"
        )

    access_token = encode_jwt_token(
        payload={"email": request.email}, lifespan=datetime.timedelta(minutes=15)
    )
    refresh_token = generate_refresh_token()
    await RefreshToken.insert(
        session,
        user.id,
        hash_value(refresh_token),
        datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=31),
    )

    return Token(access_token=access_token, refresh_token=refresh_token)


@auth_router.post("/refresh")
async def refresh_token(
    session: SessionDependency, request: RefreshTokenRequest
) -> None: ...


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(session: SessionDependency, request: UserAuthRequest) -> None:
    try:
        await User.insert(session, request.email, request.password)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already in use"
        )


AuthDependency = Annotated[str, Depends(get_authentication_header)]
UserDependency = Annotated[User, Depends(get_signed_user)]
