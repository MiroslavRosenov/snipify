from typing import Annotated, Optional

from loguru import logger as log

from fastapi import Depends
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import BusyLoadingError, ConnectionError, TimeoutError

from app.config import Config


class RedisClient:
    instance: Optional["RedisClient"] = None
    client: Redis

    # Errors that are worth retrying – transient connectivity / load issues.
    _retry_on = (ConnectionError, TimeoutError, BusyLoadingError)

    @classmethod
    def get_instance(cls, redis_url: str) -> "RedisClient":
        if cls.instance is not None:
            return cls.instance

        cls.client = Redis.from_url(
            redis_url,
            decode_responses=True,
            retry=Retry(ExponentialBackoff(cap=10, base=0.1), retries=3),
            retry_on_error=list(cls._retry_on),
            health_check_interval=30,
            socket_connect_timeout=5,
            socket_timeout=5,
            socket_keepalive=True,
        )

        log.success("Successfully created Redis client from URL")
        cls.instance = cls
        return cls

    @classmethod
    async def cleanup(cls) -> None:
        if not cls.instance:
            return

        await cls.client.aclose()
        cls.instance = None
        log.info("Redis client cleaned up")

    @classmethod
    async def ping(cls) -> bool:
        instance = cls.get_instance(Config.REDIS_URL)
        try:
            return await instance.client.ping()
        except cls._retry_on as exc:
            log.opt(exception=exc).error("Redis ping failed - {}", exc)
            return False

    @classmethod
    async def get_client(cls) -> Redis:
        return cls.get_instance(Config.REDIS_URL).client


RedisDependency = Annotated[Redis, Depends(RedisClient.get_client)]
