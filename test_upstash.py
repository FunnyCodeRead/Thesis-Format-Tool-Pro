import asyncio

from app.core.config import settings
from upstash_redis.asyncio import Redis


async def main() -> None:
    redis = Redis(
        url=settings.upstash_redis_rest_url,
        token=(
            settings
            .upstash_redis_rest_token
            .get_secret_value()
        ),
        allow_telemetry=False,
    )

    await redis.set(
        "thesis:test",
        "ok",
        ex=30,
    )

    value = await redis.get("thesis:test")

    print("Upstash value:", value)

    await redis.delete("thesis:test")


if __name__ == "__main__":
    asyncio.run(main())