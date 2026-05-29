import datetime
from typing import Annotated, Optional

from fastapi import Depends
from sqlalchemy import func, select, insert, update, Integer, Text, Boolean, DateTime
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
        statement = insert(Url).values(origin=url, alias=alias, created_by=created_by)
        await session.execute(statement)
        await session.commit()

    @staticmethod
    async def get_url_row(session: AsyncSession, url: str):
        statement = select(Url).where(lower(Url.origin) == lower(url))
        result = await session.execute(statement)

        return result.scalar_one_or_none()

    @staticmethod
    async def get_url_from_alias(session: AsyncSession, alias: str):
        statement = select(Url).where(lower(Url.alias) == lower(alias))
        result = await session.execute(statement)

        return result.scalar_one_or_none()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))

    @staticmethod
    async def fetch_user(session: AsyncSession, email: str) -> Optional["User"]:
        statement = select(User).where(lower(User.email) == lower(email))
        result = await session.execute(statement)

        return result.scalar_one_or_none()

    @staticmethod
    async def insert(session: AsyncSession, email: str, password: str) -> None:
        from app.api.routers.security import hash_value  # Circular import issue

        statement = insert(User).values(
            email=email, hashed_password=hash_value(password)
        )
        await session.execute(statement)
        await session.commit()


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
        statement = insert(RefreshToken).values(
            owner_id=owner_id, refresh_token=refresh_token, expires_at=expires_at
        )
        await session.execute(statement)
        await session.commit()

    @staticmethod
    async def update_refresh_token(
        session: AsyncSession, old_value: str, new_value: str
    ) -> None:
        statement = (
            update(RefreshToken)
            .where(RefreshToken.refresh_token == old_value)
            .values(refresh_token=new_value)
        )
        await session.execute(statement)
        await session.commit()

    @staticmethod
    async def is_owner_at_limit(session: AsyncSession, owner_id: int) -> bool:
        statement = select(RefreshToken).where(RefreshToken.owner_id == owner_id)
        result = await session.execute(statement)
        rows = result.all()

        return len(rows) >= Config.MAX_SESIONS_PER_USER


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
                except Exception:
                    await session.rollback()
                    raise


SessionDependency = Annotated[AsyncSession, Depends(DatabaseClient.get_session)]
