from typing import Optional

from loguru import logger as log
from decouple import config


class Config:
    ENVIRONMENT: str = config("ENVIRONMENT", default="local")
    DATABASE_URL: str = config("DATABASE_URL")
    REDIS_URL: str = config("REDIS_URL")

    SECRET_KEY: str = config("SECRET_KEY")
    ALGORITHM: str = config("ALGORITHM")
    MAX_SESIONS_PER_USER: int = config("MAX_SESIONS_PER_USER", cast=int, default=3)

    SMTP_SERVER: Optional[str] = config("SMTP_SERVER", default=None)
    SMTP_PORT: int = config("SMTP_PORT", cast=int, default=587)
    SMTP_LOGIN: Optional[str] = config("SMTP_LOGIN", default=None)
    SMTP_PASSWORD: Optional[str] = config("SMTP_PASSWORD", default=None)
    SMTP_USE_SSL: bool = config("SMTP_USE_SSL", cast=bool, default=False)
    SMTP_FROM_NAME: str = config("SMTP_FROM_NAME", default=None)
    SMTP_FROM_EMAIL: str = config("SMTP_FROM_EMAIL", default=None)

    # Contact / legal details surfaced in the UI and policy pages.
    CONTACT_EMAIL: str = config("CONTACT_EMAIL", default="-")
    LEGAL_EFFECTIVE_DATE: str = config("LEGAL_EFFECTIVE_DATE", default="-")
    LEGAL_GOVERNING_LAW: str = config("LEGAL_GOVERNING_LAW", default="-")

    @classmethod
    def validate_environment(cls, value: str) -> None:
        allowed_environments = ("local", "dev", "production")

        if str(value).casefold() not in allowed_environments:
            raise RuntimeError(
                f"Invalid 'ENVIRONMENT' provided - {value}, ensure that in match any of ({allowed_environments})"
            )

    @classmethod
    def validate_config(cls) -> None:
        for func, params in [(cls.validate_environment, cls.ENVIRONMENT)]:
            try:
                if params:
                    func(params)
                else:
                    func()

            except Exception as exc:
                log.warning("Failed to validate '{}' - {}", func.__name__, exc)
                raise exc

            else:
                log.success("Successfully validated '{}'", func.__name__)

    @classmethod
    def is_development_environment(cls) -> bool:
        return cls.ENVIRONMENT in ("local", "dev")

    @classmethod
    def use_secure_cookies(cls) -> bool:
        return not cls.is_development_environment()

    @classmethod
    def smtp_configured(cls) -> bool:
        return all(
            (
                cls.SMTP_SERVER,
                cls.SMTP_LOGIN,
                cls.SMTP_PASSWORD,
                cls.SMTP_FROM_NAME,
                cls.SMTP_FROM_EMAIL,
            )
        )
