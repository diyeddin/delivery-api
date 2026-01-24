"""Trigger the reclaim task in-process for quick testing.

Usage: python scripts/trigger_reclaim.py

This will call the Celery task function directly (not via broker) so it runs
in the same process and updates the DB immediately. Useful for local manual
verification when you manually set an order.assigned_at to >10 minutes ago.
"""
from app.tasks.order_tasks import reclaim_expired_assignments


def main():
    count = reclaim_expired_assignments.run()
    print(f"Reclaimed {count} orders")


if __name__ == "__main__":
    main()
