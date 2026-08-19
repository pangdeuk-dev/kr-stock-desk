from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import opinions

KST = ZoneInfo("Asia/Seoul")
_scheduler: BackgroundScheduler | None = None


def _safe_morning() -> None:
    try:
        opinions.generate_opinion("morning")
    except Exception as exc:
        print("morning job failed:", exc)


def _safe_opinion() -> None:
    try:
        opinions.generate_opinion("opinion")
    except Exception as exc:
        print("opinion job failed:", exc)


def start() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler(timezone=KST)
    _scheduler.add_job(
        _safe_morning,
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone=KST),
        id="morning",
        replace_existing=True,
    )
    _scheduler.add_job(
        _safe_opinion,
        CronTrigger(hour=11, minute=0, day_of_week="mon-fri", timezone=KST),
        id="opinion",
        replace_existing=True,
    )
    _scheduler.start()
    try:
        opinions.catch_up_if_needed()
    except Exception as exc:
        print("catch-up failed:", exc)
