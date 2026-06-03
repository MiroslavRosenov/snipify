from __future__ import annotations

import datetime
import secrets
import jwt

from hashlib import sha256
from pwdlib.exceptions import UnknownHashError
from sqlalchemy.exc import IntegrityError
from loguru import logger as log
from typing import Annotated, Dict, Optional
from pwdlib import PasswordHash

from fastapi import HTTPException, Request, Response, status, Depends
from fastapi.routing import APIRouter

from app.config import Config
from app.models.database import RefreshToken, SessionDependency, User
from app.models.requests import UserAuthRequest

auth_router = APIRouter(prefix="/authentication")
password_hash = PasswordHash.recommended()


def verify_password(value: str, hashed_value: str) -> bool:
    try:
        return password_hash.verify(value, hashed_value)
    except UnknownHashError as exc:
        log.opt(exception=exc).error(
            "Failed to verify hash ('{}' with '{}') - {}", value, hashed_value, exc
        )
        return False


def hash_password(value: str) -> str:
    try:
        return password_hash.hash(value)
    except Exception as exc:
        log.opt(exception=exc).error(
            "Failed to hash value ('{}' with '{}') - {}", value, exc
        )
        raise exc


def hash_value(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


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
        log.warning("Failed to decode JWT token ({}) - authentication expired", token)
        raise exc

    except jwt.InvalidSignatureError as exc:
        log.warning("Failed to decode JWT token ({}) - invalid signature", token)
        raise exc

    except Exception as exc:
        log.opt(exception=exc).error(
            "Failed to decode JWT token ({}) - {}", token, str(exc)
        )
        raise exc


async def get_signed_user(
    session: SessionDependency,
    http_request: Request,
    http_response: Response,
) -> Optional[User]:
    access_token, refresh_token = (
        http_request.cookies.get("access_token"),
        http_request.cookies.get("refresh_token"),
    )

    if not any((access_token, refresh_token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        assert access_token is not None
        payload = decode_jwt_token(access_token)

        return await User.get_by_email(session, payload["sub"])

    except (
        jwt.ExpiredSignatureError,
        AssertionError,
    ):  # Here we'll do silent retry to refresh the access token with the provided refresh token and rorate the refresh
        if (
            refresh_token is not None
            and (
                stored_refresh_token := await RefreshToken.get(
                    session, hash_value(refresh_token)
                )
            )
            is not None
        ):
            user = await User.get_by_id(session, stored_refresh_token.owner_id)
            access_token_lifespan = datetime.timedelta(minutes=15)
            access_token = encode_jwt_token(
                payload={"sub": user.email}, lifespan=access_token_lifespan
            )

            refresh_token_lifespan = datetime.timedelta(days=31)
            refresh_token = generate_refresh_token()

            log.warning(
                "Automatically refreshing JWT access token for user ({}) and rotating credentials",
                stored_refresh_token.owner_id,
            )
            await RefreshToken.update_refresh_token(
                session,
                stored_refresh_token.refresh_token,  # The value is already hashed in the database
                hash_value(refresh_token),
            )

            http_response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                httponly=True,
                secure=Config.use_secure_cookies(),
                samesite="lax",
                max_age=int(refresh_token_lifespan.total_seconds()),
            )

            http_response.set_cookie(
                key="access_token",
                value=access_token,
                httponly=True,
                secure=Config.use_secure_cookies(),
                samesite="lax",
                max_age=int(access_token_lifespan.total_seconds()),
            )

            return await User.get_by_id(session, stored_refresh_token.owner_id)

        else:
            log.warning(
                "Received unathorized request without access and refresh token!"
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    except jwt.InvalidSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    except Exception as exc:
        log.opt(exception=exc).error("Failed to authenticate user - {}", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@auth_router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def create_token(
    session: SessionDependency, request: UserAuthRequest, http_response: Response
) -> None:
    if not (
        user := await User.get_by_email(session, request.email)
    ) or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The user account is not active"
        )

    if await RefreshToken.is_owner_at_limit(session, user.id):
        await RefreshToken.drop_last_refresh_token(session, user.id)

    access_token_lifespan = datetime.timedelta(minutes=15)
    access_token = encode_jwt_token(
        payload={"sub": user.email}, lifespan=access_token_lifespan
    )

    refresh_token_lifespan = datetime.timedelta(days=31)
    refresh_token = generate_refresh_token()

    await RefreshToken.insert(
        session,
        user.id,
        hash_value(refresh_token),
        datetime.datetime.now(tz=datetime.timezone.utc) + refresh_token_lifespan,
    )

    http_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=Config.use_secure_cookies(),
        samesite="lax",
        max_age=int(refresh_token_lifespan.total_seconds()),
    )

    http_response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=Config.use_secure_cookies(),
        samesite="lax",
        max_age=int(access_token_lifespan.total_seconds()),
    )


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDependency, http_request: Request, http_response: Response
) -> None:
    access_token, refresh_token = (
        http_request.cookies.get("access_token"),
        http_request.cookies.get("refresh_token"),
    )

    if not all((access_token, refresh_token)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    await RefreshToken.delete(session, refresh_token)

    http_response.delete_cookie("access_token")
    http_response.delete_cookie("refresh_token")


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(session: SessionDependency, request: UserAuthRequest) -> None:
    try:
        await User.insert(session, request.email, hash_password(request.password))
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)


UserDependency = Annotated[User, Depends(get_signed_user)]
