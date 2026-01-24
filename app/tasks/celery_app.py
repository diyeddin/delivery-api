import os
from celery import Celery
from celery.schedules import crontab # For more complex schedules if needed

# Use REDIS_URL env var or default to localhost
broker = os.getenv("REDIS_URL", os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))

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