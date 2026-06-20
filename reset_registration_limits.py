import asyncio

from upstash_redis.asyncio import Redis

from app.core.config import settings


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

    cursor: int | str = 0
    deleted_count = 0

    while True:
        result = await redis.execute(
            [
                "SCAN",
                str(cursor),
                "MATCH",
                "registration:*",
                "COUNT",
                "1000",
            ]
        )

        # Upstash có thể trả list hoặc tuple.
        if (
            not isinstance(result, (list, tuple))
            or len(result) != 2
        ):
            raise RuntimeError(
                f"Phản hồi SCAN không hợp lệ: {result!r}"
            )

        cursor = result[0]
        keys = result[1]

        if isinstance(keys, (list, tuple)) and keys:
            deleted = await redis.execute(
                [
                    "DEL",
                    *[str(key) for key in keys],
                ]
            )

            deleted_count += int(deleted or 0)

            print(
                f"Đã xóa {len(keys)} khóa:",
                *keys,
                sep="\n- ",
            )

        if str(cursor) == "0":
            break

    print(
        f"\nHoàn tất. Đã xóa "
        f"{deleted_count} khóa giới hạn đăng ký."
    )


if __name__ == "__main__":
    asyncio.run(main())