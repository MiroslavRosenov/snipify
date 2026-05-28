import datetime
from typing import Annotated, Optional

from fastapi import Depends
from sqlalchemy import create_engine, select, insert, func
from sqlalchemy.orm import Session, DeclarativeBase, mapped_column, Mapped

from app.config import Config
from app.models.requests import CreateUserRequest


class Base(DeclarativeBase): ...


class Url(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str]
    alias: Mapped[str]


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

        cls.engine = create_engine(
            database_url, echo=Config.is_development_environment()
        )
        return cls

    @classmethod
    def get_session(cls):
        instance = cls.get_instance(Config.DATABASE_URL)
        with Session(instance.engine) as session:
            yield session

    @staticmethod
    def get_url_row(session: Session, url: str):
        statement = select(Url).where(lower(Url.origin) == lower(url))
        result = session.execute(statement).scalar_one_or_none()

        return result

    @staticmethod
    def get_url_from_alias(session: Session, alias: str):
        statement = select(Url).where(lower(Url.alias) == lower(alias))
        result = session.execute(statement).scalar_one_or_none()

        return result

    @staticmethod
    def insert_url(session: Session, url: str, alias: str) -> None:
        statement = insert(Url).values(origin=url, alias=alias)
        session.execute(statement)
        session.commit()

    @staticmethod
    def fetch_user(session: Session, email: str) -> Optional[User]:
        statement = select(User).where(lower(User.email) == lower(email))
        result = session.execute(statement).scalar_one_or_none()

        return result

    @staticmethod
    def insert_user(session: Session, user: CreateUserRequest) -> None:
        from app.api.routers.security import hash_password  # Circular import issue

        statement = insert(User).values(
            email=user.username, hashed_password=hash_password(user.password)
        )
        session.execute(statement)
        session.commit()


SessionDependency = Annotated[Session, Depends(DatabaseClient.get_session)]
