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
from app.models.database import (
    OneTimeToken,
    OneTimeTokenPurpose,
    RefreshToken,
    SessionDependency,
    User,
)
from app.models.requests import (
    PasswordResetRequest,
    PasswordChangeRequest,
    ResetPasswordRequest,
    UserAuthRequest,
)
from app.smtp_client import SMTPClient
from app.utils import timeit

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


ACCESS_TOKEN_LIFESPAN = datetime.timedelta(minutes=15)
REFRESH_TOKEN_LIFESPAN = datetime.timedelta(days=31)
PASSWORD_RESET_LIFESPAN = datetime.timedelta(hours=1)
ACTIVATION_TOKEN_LIFESPAN = datetime.timedelta(hours=24)
ONE_TIME_TOKEN_COOLDOWN = datetime.timedelta(minutes=15)


def create_auth_tokens(email: str) -> tuple[str, str]:
    access_token = encode_jwt_token(
        payload={"sub": email}, lifespan=ACCESS_TOKEN_LIFESPAN
    )
    refresh_token = generate_refresh_token()
    return access_token, refresh_token


def set_auth_cookies(
    http_response: Response, access_token: str, refresh_token: str
) -> None:
    http_response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=Config.use_secure_cookies(),
        samesite="lax",
        max_age=int(ACCESS_TOKEN_LIFESPAN.total_seconds()),
    )
    http_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=Config.use_secure_cookies(),
        samesite="lax",
        max_age=int(REFRESH_TOKEN_LIFESPAN.total_seconds()),
    )


def delete_auth_cookies(http_response: Response) -> None:
    http_response.delete_cookie("access_token")
    http_response.delete_cookie("refresh_token")


def get_auth_cookies(http_request: Request) -> tuple[str | None, str | None]:
    return (
        http_request.cookies.get("access_token"),
        http_request.cookies.get("refresh_token"),
    )


def encode_jwt_token(*, payload: dict, lifespan: Optional[datetime.timedelta]):
    payload = payload.copy()

    now = datetime.datetime.now(datetime.timezone.utc)
    payload.update({"iat": now})

    if lifespan:
        expire = now + lifespan
        payload.update({"exp": expire})

    token = jwt.encode(payload, key=Config.SECRET_KEY, algorithm=Config.ALGORITHM)

    return token


def decode_jwt_token(*, token: str, raise_exceptions: bool = True) -> Optional[Dict]:
    try:
        payload = jwt.decode(
            token, key=Config.SECRET_KEY, algorithms=[Config.ALGORITHM]
        )
        return payload

    except jwt.ExpiredSignatureError as exc:
        log.warning("Failed to decode JWT token ({}) - authentication expired", token)

        if raise_exceptions:
            raise exc

    except jwt.InvalidSignatureError as exc:
        log.warning("Failed to decode JWT token ({}) - invalid signature", token)

        if raise_exceptions:
            raise exc

    except Exception as exc:
        log_function = log.opt(exception=exc).error if raise_exceptions else log.warning

        log_function("Failed to decode JWT token ({}) - {}", token, str(exc))

        if raise_exceptions:
            raise exc


@timeit
async def get_current_user(
    session: SessionDependency,
    http_request: Request,
    http_response: Response,
) -> Optional[User]:
    access_token, refresh_token = get_auth_cookies(http_request)

    if not any((access_token, refresh_token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        assert access_token is not None
        payload = decode_jwt_token(token=access_token)

        return await User.get_by_email(session, payload["sub"])

    except (
        jwt.ExpiredSignatureError,
        AssertionError,
    ):  # silent retry: refresh access token and rotate refresh token
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
            access_token, refresh_token = create_auth_tokens(user.email)

            log.warning(
                "Automatically refreshing JWT access token for user ({}) and rotating credentials",
                stored_refresh_token.owner_id,
            )
            await RefreshToken.update_refresh_token(
                session,
                stored_refresh_token.refresh_token,  # already hashed in the database
                hash_value(refresh_token),
            )

            set_auth_cookies(http_response, access_token, refresh_token)

            return await User.get_by_id(session, stored_refresh_token.owner_id)

        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    except jwt.InvalidSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    except Exception as exc:
        log.opt(exception=exc).error("Failed to authenticate user - {}", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    session: SessionDependency, http_request: Request, user: UserAuthRequest
) -> None:
    try:
        await User.insert(session, user.email, hash_password(user.password))
    except IntegrityError:
        log.warning("Registration attempt for already existing email ({})", user.email)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)

    registered_user = await User.get_by_email(session, user.email)
    token = encode_jwt_token(
        payload={"sub": user.email}, lifespan=ACTIVATION_TOKEN_LIFESPAN
    )
    await OneTimeToken.insert(
        session,
        owner_id=registered_user.id,
        token_hash=hash_value(token),
        purpose=OneTimeTokenPurpose.account_activation,
        expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + ACTIVATION_TOKEN_LIFESPAN,
    )

    smtp_client = SMTPClient.get_instance()
    await smtp_client.send_template(
        to=user.email,
        subject="Confirm your Snipify account",
        template="confirmation.html",
        context={
            "base_url": str(http_request.base_url._url),
            "confirmation_url": f"{http_request.base_url._url}activate?token={token}",
            "user_email": user.email,
        },
        from_name=Config.SMTP_FROM_NAME,
        from_email=Config.SMTP_FROM_EMAIL,
    )

    log.success("Registered new user ({}) and sent activation email", user.email)


@auth_router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def authenticate_user(
    session: SessionDependency, request: UserAuthRequest, http_response: Response
) -> None:
    if not (
        user := await User.get_by_email(session, request.email)
    ) or not verify_password(request.password, user.hashed_password):
        log.warning(
            "Failed login attempt for email ({}) - invalid credentials", request.email
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.active:
        log.warning("Login attempt for inactive account ({})", user.email)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This account is inactive. If you recently registered, please check your email to activate it. Deactivated accounts cannot be restored.",
        )

    if await RefreshToken.is_owner_at_limit(session, user.id):
        await RefreshToken.drop_last_refresh_token(session, user.id)

    access_token, refresh_token = create_auth_tokens(user.email)

    await RefreshToken.insert(
        session,
        user.id,
        hash_value(refresh_token),
        datetime.datetime.now(tz=datetime.timezone.utc) + REFRESH_TOKEN_LIFESPAN,
    )

    set_auth_cookies(http_response, access_token, refresh_token)

    log.success("User ({}) authenticated successfully", user.email)


@auth_router.put("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    session: SessionDependency, user: UserDependency, request: PasswordChangeRequest
) -> None:
    if not verify_password(request.current_password, user.hashed_password):
        log.warning(
            "Failed password change for user ({}) - incorrect current password",
            user.email,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password")

    await User.update_password_by_id(
        session, user.id, hash_password(request.new_password)
    )

    log.success("User ({}) changed their password", user.email)


@auth_router.post("/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def password_reset_request(
    session: SessionDependency, http_request: Request, request: PasswordResetRequest
) -> None:
    email = request.email

    user = await User.get_by_email(session, email)
    if not user:
        log.warning("Received password request for non-existing email ({})", email)
        return

    if not user.active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This account is inactive. If you recently registered, please check your email to activate it. Deactivated accounts cannot be restored.",
        )

    latest = await OneTimeToken.get_latest_for_user(
        session, user.id, OneTimeTokenPurpose.password_reset
    )
    if latest is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
        cooldown_ends = latest.created_at + ONE_TIME_TOKEN_COOLDOWN
        if now <= cooldown_ends:
            log.warning(
                "Password reset requested for ({}) while still on cooldown", email
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"A reset link was already sent recently. Please check your inbox or try again in {ONE_TIME_TOKEN_COOLDOWN.total_seconds() // 60} minutes.",
            )

    await OneTimeToken.invalidate_all_for_user(
        session, user.id, OneTimeTokenPurpose.password_reset
    )

    token = encode_jwt_token(payload={"sub": email}, lifespan=PASSWORD_RESET_LIFESPAN)
    await OneTimeToken.insert(
        session,
        owner_id=user.id,
        token_hash=hash_value(token),
        purpose=OneTimeTokenPurpose.password_reset,
        expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + PASSWORD_RESET_LIFESPAN,
    )

    smtp_client = SMTPClient.get_instance()
    await smtp_client.send_template(
        to=email,
        subject="Reset your Snipify password",
        template="password_reset.html",
        context={
            "base_url": str(http_request.base_url._url),
            "reset_url": f"{http_request.base_url._url}reset-password?token={token}",
            "user_email": email,
            "expires_in": "1 hour",
        },
        from_name=Config.SMTP_FROM_NAME,
        from_email=Config.SMTP_FROM_EMAIL,
    )

    log.success("Sent password reset email to ({})", email)


@auth_router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    session: SessionDependency, request: ResetPasswordRequest
) -> None:
    payload = decode_jwt_token(token=request.token, raise_exceptions=False)
    if payload is None:
        log.warning("Password reset attempt with invalid or expired token")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The link is invalid or already used"
        )

    stored = await OneTimeToken.get_by_hash(session, hash_value(request.token))
    if stored is None or stored.used:
        log.warning(
            "Password reset attempt with already used token for ({})", payload["sub"]
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This link has already been used"
        )

    user = await User.get_by_email(session, payload["sub"])
    if user is None:
        log.warning("Password reset attempt for non-existing user ({})", payload["sub"])
        raise HTTPException(status.HTTP_400_BAD_REQUEST)

    await OneTimeToken.invalidate_all_for_user(
        session, user.id, OneTimeTokenPurpose.password_reset
    )
    await User.update_password_by_email(
        session, payload["sub"], hash_password(request.password)
    )
    log.success(
        "Updated user password for '{}' from forgotten password request", payload["sub"]
    )


@auth_router.post("/deactivate-account", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    session: SessionDependency,
    http_request: Request,
    http_response: Response,
    user: UserDependency,
) -> None:
    email = user.email

    await User.deactivate_by_id(session, user.id)
    await RefreshToken.delete_all_for_user(session, user.id)
    await OneTimeToken.delete_all_for_user(session, user.id)

    delete_auth_cookies(http_response)

    smtp_client = SMTPClient.get_instance()
    if smtp_client is not None:
        try:
            await smtp_client.send_template(
                to=email,
                subject="Your Snipify account has been deactivated",
                template="account_deactivated.html",
                context={
                    "base_url": str(http_request.base_url._url),
                    "user_email": email,
                },
                from_name=Config.SMTP_FROM_NAME,
                from_email=Config.SMTP_FROM_EMAIL,
            )
        except Exception as exc:
            log.opt(exception=exc).error(
                "Failed to send account deactivation email to ({}) - {}", email, exc
            )

    log.success("Deactivated account for user ({}) and revoked all credentials", email)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDependency, http_request: Request, http_response: Response
) -> None:
    access_token, refresh_token = get_auth_cookies(http_request)

    if not any((access_token, refresh_token)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    await RefreshToken.delete(session, refresh_token)

    delete_auth_cookies(http_response)

    log.success("User logged out and refresh token revoked")


UserDependency = Annotated[User, Depends(get_current_user)]
