import logging
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(
            depth=6,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def setup_logging():
    logger.remove()

    logger.add(
        sys.stdout,
        level="INFO",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # IMPORTANT: do NOT touch root handlers aggressively
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
    ):
        log = logging.getLogger(name)
        log.handlers = []
        log.propagate = True
