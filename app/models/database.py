import datetime

from typing import Annotated, Optional

from fastapi import Depends
from sqlalchemy import (
    func,
    select,
    insert,
    update,
    delete,
    Integer,
    Text,
    Boolean,
    DateTime,
)
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Config

lower = func.LOWER


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
    async def get_url_row(session: AsyncSession, url: str):
        query = select(Url).where(lower(Url.origin) == lower(url))
        result = await session.execute(query)

        return result.scalar_one_or_none()

    @staticmethod
    async def get_url_from_alias(session: AsyncSession, alias: str):
        query = select(Url).where(lower(Url.alias) == lower(alias))
        result = await session.execute(query)

        return result.scalar_one_or_none()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> Optional["User"]:
        query = select(User).where(lower(User.email) == lower(email))
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


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    refresh_token: Mapped[str] = mapped_column(Text, unique=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))

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
        query = (
            select(RefreshToken)
            .join(User, RefreshToken.owner_id == User.id, full=True)
            .where(RefreshToken.refresh_token == refresh_token)
        )
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


class DatabaseClient:
    instance: Optional["DatabaseClient"] = None

    @classmethod
    def get_instance(cls, database_url: str) -> "DatabaseClient":
        if cls.instance is not None:
            return cls.instance

        cls.engine = create_async_engine(
            database_url,
            echo=Config.is_development_environment(),
            connect_args={"server_settings": {"search_path": "public"}},
        )

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
                    raise


SessionDependency = Annotated[AsyncSession, Depends(DatabaseClient.get_session)]
