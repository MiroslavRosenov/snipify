from loguru import logger as log
from decouple import config


class Config:
    ENVIRONMENT: str = config("ENVIRONMENT", default="local", cast=str)

    @classmethod
    def validate_environment(cls, value: str) -> None:
        allowed_environments = ("local", "dev", "production")

        if str(value).casefold() not in allowed_environments:
            raise RuntimeError(
                f"Invalid 'ENVIROMENT' provided - {value}, ensure that in match any of ({allowed_environments})"
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
