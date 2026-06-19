from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from upstash_redis.asyncio import Redis

from app.core.config import settings


logger = logging.getLogger(__name__)


_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])

if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end

local ttl = redis.call('TTL', KEYS[1])

return {current, ttl}
"""


_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end

return 0
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    retry_after: int


class RegistrationGuardUnavailable(Exception):
    pass


class RegistrationGuard:
    def __init__(
        self,
        *,
        redis_url: str,
        redis_token: str,
    ) -> None:
        self._redis = Redis(
            url=redis_url,
            token=redis_token,
            allow_telemetry=False,
            rest_retries=2,
            rest_retry_interval=0.5,
        )

    async def consume(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        try:
            result = await self._redis.execute(
                command=[
                    "EVAL",
                    _RATE_LIMIT_SCRIPT,
                    "1",
                    key,
                    str(window_seconds),
                ]
            )
        except Exception as exc:
            logger.exception(
                "Upstash rate limit operation failed"
            )

            raise RegistrationGuardUnavailable(
                "Upstash rate limiter unavailable."
            ) from exc

        count, ttl = self._parse_rate_limit_result(
            result
        )

        return RateLimitResult(
            allowed=count <= limit,
            count=count,
            retry_after=max(ttl, 1),
        )

    async def acquire_email_lock(
        self,
        *,
        email_hash: str,
        expires_seconds: int,
    ) -> str | None:
        token = secrets.token_urlsafe(24)
        key = self._lock_key(email_hash)

        try:
            result = await self._redis.execute(
                command=[
                    "SET",
                    key,
                    token,
                    "NX",
                    "EX",
                    str(expires_seconds),
                ]
            )
        except Exception as exc:
            logger.exception(
                "Upstash registration lock failed"
            )

            raise RegistrationGuardUnavailable(
                "Upstash registration lock unavailable."
            ) from exc

        if isinstance(result, str) and result.upper() == "OK":
            return token

        return None

    async def release_email_lock(
        self,
        *,
        email_hash: str,
        token: str,
    ) -> None:
        key = self._lock_key(email_hash)

        try:
            await self._redis.execute(
                command=[
                    "EVAL",
                    _RELEASE_LOCK_SCRIPT,
                    "1",
                    key,
                    token,
                ]
            )
        except Exception:
            # Không làm hỏng request chính.
            # Khóa vẫn tự hết hạn theo EX.
            logger.warning(
                "Could not release Upstash registration lock",
                exc_info=True,
            )

    @staticmethod
    def _lock_key(email_hash: str) -> str:
        return f"registration:lock:{email_hash}"

    @staticmethod
    def _parse_rate_limit_result(
        result: Any,
    ) -> tuple[int, int]:
        if (
            not isinstance(result, list)
            or len(result) != 2
        ):
            raise RegistrationGuardUnavailable(
                "Invalid Upstash rate limit response."
            )

        try:
            count = int(result[0])
            ttl = int(result[1])
        except (TypeError, ValueError) as exc:
            raise RegistrationGuardUnavailable(
                "Invalid Upstash rate limit values."
            ) from exc

        return count, ttl


@lru_cache
def get_registration_guard() -> RegistrationGuard:
    return RegistrationGuard(
        redis_url=settings.upstash_redis_rest_url,
        redis_token=(
            settings
            .upstash_redis_rest_token
            .get_secret_value()
        ),
    )