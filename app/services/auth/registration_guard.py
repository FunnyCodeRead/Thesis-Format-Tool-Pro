from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from upstash_redis.asyncio import Redis

from app.core.config import settings


logger = logging.getLogger(__name__)


_COMBINED_RATE_LIMIT_SCRIPT = """
local ip_count = redis.call('INCR', KEYS[1])

if ip_count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end

local email_count = redis.call('INCR', KEYS[2])

if email_count == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[2])
end

local ip_ttl = redis.call('TTL', KEYS[1])
local email_ttl = redis.call('TTL', KEYS[2])

return {
  ip_count,
  ip_ttl,
  email_count,
  email_ttl
}
"""


_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end

return 0
"""


@dataclass(frozen=True)
class RegistrationLimitResult:
    allowed: bool
    retry_after: int
    ip_count: int
    email_count: int


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
            # Không dùng thời gian retry mặc định 3 giây.
            rest_retries=1,
            rest_retry_interval=0.15,
        )

    async def consume_registration_limits(
        self,
        *,
        ip_key: str,
        email_key: str,
        ip_limit: int,
        email_limit: int,
        ip_window_seconds: int,
        email_window_seconds: int,
    ) -> RegistrationLimitResult:
        try:
            result = await self._redis.eval(
                _COMBINED_RATE_LIMIT_SCRIPT,
                keys=[ip_key, email_key],
                args=[
                    str(ip_window_seconds),
                    str(email_window_seconds),
                ],
            )
        except Exception as exc:
            logger.exception(
                "Upstash registration rate limit failed"
            )
            raise RegistrationGuardUnavailable(
                "Registration rate limiter unavailable."
            ) from exc

        values = self._parse_integer_list(
            result,
            expected_length=4,
        )

        ip_count, ip_ttl, email_count, email_ttl = values
        ip_allowed = ip_count <= ip_limit
        email_allowed = email_count <= email_limit

        retry_after = 0

        if not ip_allowed:
            retry_after = max(retry_after, ip_ttl, 1)

        if not email_allowed:
            retry_after = max(
                retry_after,
                email_ttl,
                1,
            )

        return RegistrationLimitResult(
            allowed=ip_allowed and email_allowed,
            retry_after=retry_after,
            ip_count=ip_count,
            email_count=email_count,
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
                [
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
                "Registration lock unavailable."
            ) from exc

        if result is True:
            return token

        if (
            isinstance(result, str)
            and result.upper() == "OK"
        ):
            return token

        return None

    async def release_email_lock(
        self,
        *,
        email_hash: str,
        token: str,
    ) -> None:
        try:
            await self._redis.eval(
                _RELEASE_LOCK_SCRIPT,
                keys=[self._lock_key(email_hash)],
                args=[token],
            )
        except Exception:
            # Khóa vẫn tự hết hạn theo EX.
            logger.warning(
                "Could not release registration lock",
                exc_info=True,
            )

    @staticmethod
    def _lock_key(email_hash: str) -> str:
        return f"registration:lock:{email_hash}"

    @staticmethod
    def _parse_integer_list(
        value: Any,
        *,
        expected_length: int,
    ) -> list[int]:
        if not isinstance(value, (list, tuple)):
            raise RegistrationGuardUnavailable(
                "Invalid Upstash response type."
            )

        if len(value) != expected_length:
            raise RegistrationGuardUnavailable(
                "Invalid Upstash response length."
            )

        try:
            return [int(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise RegistrationGuardUnavailable(
                "Invalid Upstash response values."
            ) from exc


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
