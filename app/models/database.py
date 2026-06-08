import datetime
import enum

from typing import Annotated, Awaitable, Optional
from loguru import logger as log

from fastapi import Depends
from sqlalchemy import (
    func,
    select,
    insert,
    update,
    delete,
    Enum,
    Integer,
    Text,
    Boolean,
    DateTime,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.cache import LRUCache, cached, invalidates
from app.config import Config
from app.utils import timeit

lower = func.LOWER

# Caches User rows by email for the auth hot path. Invalidated whenever a user's hashed_password or active flag changes.
# The structure is LRUCache[email, User]
user_email_cache: "LRUCache[str, User]" = LRUCache(maxsize=512)


def email_for_id(session: AsyncSession, user_id: int) -> "Awaitable[Optional[str]]":
    """Resolve a user's email by id; used as an invalidation key resolver."""
    return session.scalar(select(User.email).where(User.id == user_id))


class Base(DeclarativeBase): ...


class Url(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(unique=True, index=True)
    alias: Mapped[str] = mapped_column(unique=True, index=True)
    created_by: Mapped[int] = mapped_column(Integer)

    @staticmethod
    async def insert(
        session: AsyncSession, url: str, alias: str, created_by: int
    ) -> None:
        query = insert(Url).values(origin=url, alias=alias, created_by=created_by)
        await session.execute(query)

    @staticmethod
    @timeit
    async def get_url_row(session: AsyncSession, url: str):
        query = select(Url).where(lower(Url.origin) == lower(url))
        result = await session.execute(query)

        return result.scalar_one_or_none()

    @staticmethod
    @timeit
    async def get_url_from_alias(session: AsyncSession, alias: str):
        query = select(Url).where(lower(Url.alias) == lower(alias))
        result = await session.execute(query)

        return result.scalar_one_or_none()

    @staticmethod
    @timeit
    async def get_by_user_id(
        session: AsyncSession, user_id: int, offset: int = 0, limit: int = 10
    ) -> list["Url"]:
        query = (
            select(Url)
            .where(Url.created_by == user_id)
            .order_by(Url.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)

        return list(result.scalars().all())

    @staticmethod
    @timeit
    async def count_by_user_id(session: AsyncSession, user_id: int) -> int:
        query = select(func.count()).where(Url.created_by == user_id)
        result = await session.execute(query)

        return result.scalar_one()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    def snapshot(self) -> "User":
        """A detached, session-independent copy safe to keep in the cache.

        Caching the live ORM instance is unsafe: the session expires its
        attributes on commit, so a later read would raise DetachedInstanceError.
        """
        return User(
            id=self.id,
            email=self.email,
            hashed_password=self.hashed_password,
            active=self.active,
            created_at=self.created_at,
        )

    @staticmethod
    @timeit
    @cached(
        cache=user_email_cache,
        key=lambda session, email: email,
        store=lambda user: user.snapshot(),
    )
    async def get_by_email(session: AsyncSession, email: str) -> Optional["User"]:
        query = select(User).where(User.email == email)
        result = await session.execute(query)

        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, id: int) -> Optional["User"]:
        query = select(User).where(User.id == id)
        result = await session.execute(query)

        return result.scalar_one_or_none()

    @staticmethod
    async def insert(session: AsyncSession, email: str, password: str) -> None:
        query = insert(User).values(email=email, hashed_password=password)
        await session.execute(query)

    @staticmethod
    @invalidates(
        cache=user_email_cache,
        key=lambda session, user_id, password_hash: email_for_id(session, user_id),
    )
    async def update_password_by_id(
        session: AsyncSession, user_id: int, password_hash: str
    ) -> None:
        query = (
            update(User).values(hashed_password=password_hash).where(User.id == user_id)
        )
        await session.execute(query)

    @staticmethod
    @invalidates(
        cache=user_email_cache,
        key=lambda session, email, password_hash: email,
    )
    async def update_password_by_email(
        session: AsyncSession, email: str, password_hash: str
    ) -> None:
        query = (
            update(User)
            .values(hashed_password=password_hash)
            .where(User.email == email)
        )
        await session.execute(query)

    @staticmethod
    @invalidates(
        cache=user_email_cache,
        key=lambda session, user_id: email_for_id(session, user_id),
    )
    async def activate_by_id(session: AsyncSession, user_id: int) -> None:
        query = update(User).values(active=True).where(User.id == user_id)
        await session.execute(query)

    @staticmethod
    @invalidates(
        cache=user_email_cache,
        key=lambda session, user_id: email_for_id(session, user_id),
    )
    async def deactivate_by_id(session: AsyncSession, user_id: int) -> None:
        query = update(User).values(active=False).where(User.id == user_id)
        await session.execute(query)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    refresh_token: Mapped[str] = mapped_column(Text, unique=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    @staticmethod
    async def insert(
        session: AsyncSession,
        owner_id: int,
        refresh_token: str,
        expires_at: datetime.datetime,
    ) -> None:
        query = insert(RefreshToken).values(
            owner_id=owner_id, refresh_token=refresh_token, expires_at=expires_at
        )
        await session.execute(query)

    @staticmethod
    async def update_refresh_token(
        session: AsyncSession, old_value: str, new_value: str
    ) -> None:
        query = (
            update(RefreshToken)
            .where(RefreshToken.refresh_token == old_value)
            .values(refresh_token=new_value)
        )
        await session.execute(query)

    @staticmethod
    async def is_owner_at_limit(session: AsyncSession, owner_id: int) -> bool:
        query = select(RefreshToken).where(RefreshToken.owner_id == owner_id)
        result = await session.execute(query)
        rows = result.all()

        return len(rows) >= Config.MAX_SESIONS_PER_USER

    @staticmethod
    async def get(
        session: AsyncSession, refresh_token: str
    ) -> Optional["RefreshToken"]:
        query = select(RefreshToken).where(RefreshToken.refresh_token == refresh_token)
        result = await session.execute(query)

        return result.scalar_one_or_none()

    @staticmethod
    async def drop_last_refresh_token(session: AsyncSession, owner_id: int) -> None:
        sub_query = (
            select(RefreshToken)
            .where(RefreshToken.owner_id == owner_id)
            .order_by(RefreshToken.created_at.asc())
            .limit(1)
        )
        query = delete(RefreshToken).where(RefreshToken.id == sub_query.c.id)

        await session.execute(query)

    @staticmethod
    async def delete(session: AsyncSession, refresh_token: str) -> None:
        query = delete(RefreshToken).where(RefreshToken.refresh_token == refresh_token)
        await session.execute(query)

    @staticmethod
    async def delete_all_for_user(session: AsyncSession, owner_id: int) -> None:
        query = delete(RefreshToken).where(RefreshToken.owner_id == owner_id)
        await session.execute(query)


class OneTimeTokenPurpose(enum.Enum):
    password_reset = "password_reset"
    account_activation = "account_activation"


_purpose_enum = Enum(
    OneTimeTokenPurpose,
    name="one_time_token_purpose",
    schema="public",
    create_type=False,
)


class OneTimeToken(Base):
    __tablename__ = "one_time_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    purpose: Mapped[OneTimeTokenPurpose] = mapped_column(_purpose_enum)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    @staticmethod
    async def insert(
        session: AsyncSession,
        owner_id: int,
        token_hash: str,
        purpose: OneTimeTokenPurpose,
        expires_at: datetime.datetime,
    ) -> None:
        query = insert(OneTimeToken).values(
            owner_id=owner_id,
            token_hash=token_hash,
            purpose=purpose.value,
            expires_at=expires_at,
        )
        await session.execute(query)

    @staticmethod
    async def get_by_hash(
        session: AsyncSession, token_hash: str
    ) -> Optional["OneTimeToken"]:
        query = select(OneTimeToken).where(OneTimeToken.token_hash == token_hash)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_for_user(
        session: AsyncSession, owner_id: int, purpose: OneTimeTokenPurpose
    ) -> Optional["OneTimeToken"]:
        query = (
            select(OneTimeToken)
            .where(
                OneTimeToken.owner_id == owner_id,
                OneTimeToken.purpose == purpose,
            )
            .order_by(OneTimeToken.created_at.desc())
            .limit(1)
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def invalidate_all_for_user(
        session: AsyncSession, owner_id: int, purpose: OneTimeTokenPurpose
    ) -> None:
        query = (
            update(OneTimeToken)
            .where(
                OneTimeToken.owner_id == owner_id,
                OneTimeToken.purpose == purpose,
                OneTimeToken.used == False,  # noqa: E712
            )
            .values(used=True)
        )
        await session.execute(query)

    @staticmethod
    async def delete_all_for_user(session: AsyncSession, owner_id: int) -> None:
        query = delete(OneTimeToken).where(OneTimeToken.owner_id == owner_id)
        await session.execute(query)


class DatabaseClient:
    instance: Optional["DatabaseClient"] = None

    @classmethod
    def get_instance(cls, database_url: str) -> "DatabaseClient":
        if cls.instance is not None:
            return cls.instance

        cls.engine = create_async_engine(
            database_url,
            # The DB is remote, so a fresh connection costs ~800ms to hand-shake.
            # Keep a warm pool and never hand out a dead connection:
            #  - pool_pre_ping: cheaply verify a connection before use, so one the
            #    remote dropped while idle is transparently replaced instead of
            #    stalling/erroring on the next request.
            #  - pool_recycle: proactively retire connections older than 5 min,
            #    staying under the idle timeouts of most managed PGs / NAT / LBs.
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"server_settings": {"search_path": "public"}},
        )

        log.success("Successfully created async engine from URL")
        cls.instance = cls
        return cls

    @classmethod
    async def cleanup(cls) -> None:
        if not cls.instance:
            return

        await cls.engine.dispose()

    @classmethod
    async def get_session(cls):
        instance = cls.get_instance(Config.DATABASE_URL)
        async with AsyncSession(instance.engine) as session:
            async with session.begin():
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    await session.invalidate()
                    raise


SessionDependency = Annotated[AsyncSession, Depends(DatabaseClient.get_session)]
