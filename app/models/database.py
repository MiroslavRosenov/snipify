import datetime
from typing import Annotated, Optional

from fastapi import Depends
from sqlalchemy import select, insert, func
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Config
from app.models.requests import UserAuthRequest


class Base(DeclarativeBase): ...


class Url(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str]
    alias: Mapped[str]
    created_by: Mapped[int]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int]
    email: Mapped[str] = mapped_column(primary_key=True)
    hashed_password: Mapped[str]
    verified: Mapped[bool]
    created_at: Mapped[datetime.datetime]


lower = func.LOWER


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

    @staticmethod
    async def insert_url(
        session: AsyncSession, url: str, alias: str, created_by: int
    ) -> None:
        statement = insert(Url).values(origin=url, alias=alias, created_by=created_by)
        await session.execute(statement)
        await session.commit()

    @staticmethod
    async def fetch_user(session: AsyncSession, email: str) -> Optional[User]:
        statement = select(User).where(lower(User.email) == lower(email))
        result = await session.execute(statement)

        return result.scalar_one_or_none()

    @staticmethod
    async def insert_user(session: AsyncSession, user: UserAuthRequest) -> None:
        from app.api.routers.security import hash_password  # Circular import issue

        statement = insert(User).values(
            email=user.email, hashed_password=hash_password(user.password)
        )
        await session.execute(statement)
        await session.commit()


SessionDependency = Annotated[AsyncSession, Depends(DatabaseClient.get_session)]
