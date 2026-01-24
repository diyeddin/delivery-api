from datetime import datetime, timezone, timedelta
from typing import int as _int
from app.tasks.celery_app import celery_app
from app.core.config import settings

# Use synchronous SQLAlchemy engine inside Celery worker for simplicity
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import models


def _get_sync_db_url():
    db_url = settings.DATABASE_URL
    # If using async driver prefix, convert back to sync
    if db_url.startswith("postgresql+asyncpg://"):
        return db_url.replace("postgresql+asyncpg://", "postgresql://")
    return db_url


SYNC_DB_URL = _get_sync_db_url()
engine = create_engine(SYNC_DB_URL)
SessionLocal = sessionmaker(bind=engine)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reclaim_expired_assignments(self):
    """Find orders assigned more than 10 minutes ago and revert them to confirmed.

    Returns the number of orders reverted.
    """
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expiry_threshold = now - timedelta(minutes=10)

        stmt = select(models.Order).where(
            models.Order.status == models.OrderStatus.assigned,
            models.Order.assigned_at <= expiry_threshold,
        )

        orders = session.execute(stmt).scalars().all()
        reverted = 0
        for order in orders:
            order.driver_id = None
            order.status = models.OrderStatus.confirmed
            order.assigned_at = None
            reverted += 1

        if reverted:
            session.commit()
        return reverted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Notification tasks moved to app.tasks.notification_tasks
