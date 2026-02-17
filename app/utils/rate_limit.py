from fastapi import HTTPException, status
from app.core.redis import redis_client


async def check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> None:
    """
    Increment a Redis counter for `key` and raise 429 if `max_attempts` is exceeded
    within `window_seconds`.
    """
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, window_seconds)
    if count > max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
