import os
from celery import Celery
from app.core.config import settings

# Use REDIS_URL env var or default to localhost
broker = os.getenv("REDIS_URL", os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))

celery_app = Celery(
    "mall_delivery",
    broker=broker,
    backend=broker,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
