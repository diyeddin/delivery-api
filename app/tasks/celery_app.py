import os
from celery import Celery
from app.core.config import settings
from celery.schedules import crontab # For more complex schedules if needed

# Use REDIS_URL env var or default to localhost
broker = settings.REDIS_URL

celery_app = Celery(
    "mall_delivery",
    broker=broker,
    backend=broker,
    # CRITICAL: Tell Celery where to look for tasks
    include=['app.tasks.order_tasks', 'app.tasks.notification_tasks']
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # CRITICAL: The Beat Schedule
    beat_schedule={
        'reclaim-stale-orders-every-minute': {
            'task': 'app.tasks.order_tasks.reclaim_expired_assignments',
            'schedule': 60.0,  # Run every 60 seconds
        },
    }
)