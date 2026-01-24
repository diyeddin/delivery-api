"""Set an order's assigned_at to N minutes ago for manual testing.

Usage: python scripts/set_order_assigned_at.py <order_id> [minutes]

This will use the same sync DB connection used by Celery tasks.
"""
import sys
from datetime import datetime, timezone, timedelta
from app.core.config import settings
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import models


def _get_sync_db_url():
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgresql+asyncpg://"):
        return db_url.replace("postgresql+asyncpg://", "postgresql://")
    return db_url


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/set_order_assigned_at.py <order_id> [minutes]")
        sys.exit(1)

    order_id = int(sys.argv[1])
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    engine = create_engine(_get_sync_db_url())
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        order = session.get(models.Order, order_id)
        if not order:
            print(f"Order {order_id} not found")
            return
        order.assigned_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        order.status = models.OrderStatus.assigned
        if not order.driver_id:
            order.driver_id = 1
        session.commit()
        print(f"Set order {order_id}.assigned_at to {minutes} minutes ago")
    finally:
        session.close()


if __name__ == "__main__":
    main()
