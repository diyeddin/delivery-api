from celery import Celery
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True)
def notify_user(self, user_email: str, subject: str, body: str):
    """Notification task placeholder — send email/SMS in production.

    Currently a simple print for local/dev testing.
    """
    print(f"Notify {user_email}: {subject}\n{body}")
    return True
