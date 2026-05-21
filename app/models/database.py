from typing import Annotated, Optional

from fastapi import Depends
from sqlalchemy import create_engine, select, insert, func
from sqlalchemy.orm import Session, DeclarativeBase, mapped_column, Mapped

from app.config import Config


class Base(DeclarativeBase): ...


class Url(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str]
    alias: Mapped[str]


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
        statement = select(Url).where(func.lower(Url.origin) == func.lower(url))
        result = session.execute(statement).scalar_one_or_none()

        return result

    @staticmethod
    def get_url_from_alias(session: Session, alias: str):
        statement = select(Url).where(func.lower(Url.alias) == func.lower(alias))
        result = session.execute(statement).scalar_one_or_none()

        return result

    @staticmethod
    def insert_url(session: Session, url: str, alias: str) -> None:
        statement = insert(Url).values(origin=url, alias=alias)
        session.execute(statement)
        session.commit()


SessionDep = Annotated[Session, Depends(DatabaseClient.get_session)]
