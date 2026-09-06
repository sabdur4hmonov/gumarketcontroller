"""Celery application and beat schedule.

Two periodic jobs:
  * every minute  -- the send tick (CP6)
  * nightly       -- the materializer (CP5)

WINDOWS: the default prefork pool does not work here. Locally run

    celery -A gulbot.worker.app worker --pool=solo --loglevel=info
    celery -A gulbot.worker.app beat --loglevel=info

The VPS runs prefork. Note that a solo pool in ONE process cannot race by
construction -- the concurrency test starts two separate worker PROCESSES for
exactly that reason.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from gulbot.config import get_settings

settings = get_settings()

app = Celery(
    "gulbot",
    broker=settings.redis_url(settings.redis_db_broker),
    backend=settings.redis_url(settings.redis_db_results),
    include=["gulbot.worker.tasks"],
)

app.conf.update(
    timezone=settings.timezone,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "send-due-reminders": {
            "task": "gulbot.send_due_reminders",
            "schedule": 60.0,
        },
        # CP10b. A SEPARATE task from the reminder tick, not a branch inside it:
        # the two outboxes fail independently, and one wedged on a Telegram
        # outage must not stop the other. It also keeps the log lines readable.
        "send-order-pings": {
            "task": "gulbot.send_order_pings",
            "schedule": 60.0,
        },
        "materialize-nightly": {
            "task": "gulbot.materialize_all_shops",
            # 03:00 Asia/Tashkent: well clear of the 09:00-20:00 send window.
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
