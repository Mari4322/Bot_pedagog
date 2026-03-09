from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
import aiosqlite

from database.queries import reset_daily_counts, deactivate_expired_without_renew


def start_scheduler(*, bot: Bot, db: aiosqlite.Connection, timezone: str) -> AsyncIOScheduler:
    tz = ZoneInfo(timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(
        reset_daily_counts,
        CronTrigger(hour=0, minute=0),
        kwargs={"db": db},
        id="reset_daily_counts",
        replace_existing=True,
    )

    scheduler.add_job(
        deactivate_expired_without_renew,
        CronTrigger(hour=0, minute=1),
        kwargs={"db": db},
        id="deactivate_expired",
        replace_existing=True,
    )

    # Напоминания за 1 день (2-й этап) — добавим позже вместе с оплатой/next_payment_at.

    scheduler.start()
    return scheduler

