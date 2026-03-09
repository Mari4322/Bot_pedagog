from __future__ import annotations

"""
Планировщик задач APScheduler (timezone UTC+7).

Задачи:
  00:00    — сброс daily_count = 0 для всех пользователей
  00:01    — для подписок: если next_payment_at < сейчас и auto_renew=False → is_active=False
  00:02    — для подписок: если до next_payment_at остался ~1 день → напоминание пользователю
  каждый час (*/1) — проверка баланса polza.ai:
               • при балансе ниже порога → предупреждение администратору
               • при ошибке запроса      → уведомление администратору
"""

import logging
from datetime import datetime, timezone

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
import aiosqlite

from database.queries import (
    deactivate_expired_without_renew,
    get_users_expiring_tomorrow,
    reset_daily_counts,
)
from services.balance_service import get_balance

_log = logging.getLogger("scheduler")


async def _task_reset_daily(db: aiosqlite.Connection) -> None:
    """00:00 — сбрасываем daily_count для всех пользователей."""
    try:
        await reset_daily_counts(db)
        _log.info("[scheduler] daily_count сброшен для всех пользователей")
    except Exception as e:
        _log.exception("[scheduler] Ошибка при сбросе daily_count: %s", e)


async def _task_deactivate_expired(db: aiosqlite.Connection) -> None:
    """00:01 — деактивируем пользователей с истёкшей подпиской и auto_renew=False."""
    try:
        count = await deactivate_expired_without_renew(db)
        _log.info("[scheduler] Деактивировано пользователей с истёкшей подпиской: %d", count)
    except Exception as e:
        _log.exception("[scheduler] Ошибка при деактивации подписок: %s", e)


async def _task_remind_expiring(bot: Bot, db: aiosqlite.Connection) -> None:
    """
    00:02 — находим пользователей, у которых next_payment_at ровно через ~1 день
    (окно 23–25 часов), и отправляем им напоминание.
    """
    try:
        users = await get_users_expiring_tomorrow(db)
        _log.info("[scheduler] Пользователей с подпиской через ~1 день: %d", len(users))

        for user in users:
            tg_id = user["tg_id"]
            tariff = user.get("tariff", "")
            next_pay = user.get("next_payment_at", "")

            # Форматируем дату для читаемости
            try:
                dt = datetime.fromisoformat(next_pay)
                date_str = dt.strftime("%d.%m.%Y")
            except Exception:
                date_str = str(next_pay)

            text = (
                "⏰ <b>Напоминание о подписке</b>\n\n"
                f"Завтра истекает ваш тариф <b>{tariff}</b>.\n"
                f"Дата следующего платежа: <b>{date_str}</b>\n\n"
                "Чтобы продолжить пользоваться ботом — обновите подписку: /pay\n"
                "Для отписки (доступ останется до конца периода): /cancel_sub"
            )

            try:
                await bot.send_message(tg_id, text)
                _log.info("[scheduler] Напоминание отправлено пользователю %d", tg_id)
            except Exception as send_err:
                # Пользователь мог заблокировать бота — логируем и продолжаем
                _log.warning(
                    "[scheduler] Не удалось отправить напоминание пользователю %d: %s",
                    tg_id,
                    send_err,
                )

    except Exception as e:
        _log.exception("[scheduler] Ошибка в задаче напоминаний: %s", e)


async def _task_check_balance(
    bot: Bot,
    admin_tg_id: int,
    polza_api_key: str,
    balance_threshold: float,
) -> None:
    """
    Каждый час — запрашиваем баланс polza.ai.
    Если баланс ниже порога → предупреждение админу.
    Если запрос не удался    → уведомление админу.
    """
    try:
        balance = await get_balance(polza_api_key)
        _log.info("[scheduler] Баланс polza.ai: %.2f руб. (порог: %.2f)", balance, balance_threshold)

        if balance < balance_threshold:
            _log.warning("[scheduler] Баланс ниже порога! %.2f < %.2f", balance, balance_threshold)
            try:
                await bot.send_message(
                    admin_tg_id,
                    f"⚠️ <b>Внимание! Низкий баланс polza.ai</b>\n\n"
                    f"💰 Текущий баланс: <b>{balance:.2f} руб.</b>\n"
                    f"🔔 Порог предупреждения: <b>{balance_threshold:.0f} руб.</b>\n\n"
                    f"Пополните счёт, чтобы бот продолжал работать.",
                )
            except Exception as send_err:
                _log.warning("[scheduler] Не удалось уведомить админа о балансе: %s", send_err)

    except RuntimeError as e:
        _log.error("[scheduler] Не удалось проверить баланс: %s", e)
        try:
            await bot.send_message(
                admin_tg_id,
                f"❗ <b>Не удалось проверить баланс polza.ai</b>\n\n{e}",
            )
        except Exception:
            pass


def start_scheduler(
    *,
    bot: Bot,
    db: aiosqlite.Connection,
    timezone: str,
    admin_tg_id: int,
    polza_api_key: str,
    balance_threshold: float,
) -> AsyncIOScheduler:
    tz = ZoneInfo(timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    # 00:00 — сброс daily_count
    scheduler.add_job(
        _task_reset_daily,
        CronTrigger(hour=0, minute=0, timezone=tz),
        kwargs={"db": db},
        id="reset_daily_counts",
        replace_existing=True,
    )

    # 00:01 — деактивация истёкших подписок без auto_renew
    scheduler.add_job(
        _task_deactivate_expired,
        CronTrigger(hour=0, minute=1, timezone=tz),
        kwargs={"db": db},
        id="deactivate_expired",
        replace_existing=True,
    )

    # 00:02 — напоминание за ~1 день до истечения подписки
    scheduler.add_job(
        _task_remind_expiring,
        CronTrigger(hour=0, minute=2, timezone=tz),
        kwargs={"bot": bot, "db": db},
        id="remind_expiring",
        replace_existing=True,
    )

    # Каждый час — проверка баланса polza.ai
    scheduler.add_job(
        _task_check_balance,
        CronTrigger(minute=0, timezone=tz),   # в начале каждого часа
        kwargs={
            "bot": bot,
            "admin_tg_id": admin_tg_id,
            "polza_api_key": polza_api_key,
            "balance_threshold": balance_threshold,
        },
        id="check_balance",
        replace_existing=True,
    )

    scheduler.start()
    _log.info("[scheduler] Запущен (timezone=%s), задач: 4", timezone)
    return scheduler
