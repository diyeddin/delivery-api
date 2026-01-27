import redis.asyncio as redis
from app.core.config import settings
import os

REDIS_URL = settings.REDIS_URL

# The global redis instance
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

async def get_redis():
    return redis_client