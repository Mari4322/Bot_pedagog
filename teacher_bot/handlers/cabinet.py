from __future__ import annotations

from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database.queries import get_subscription, get_user


router = Router()


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except Exception:
        return iso


@router.message(Command("cabinet"))
async def cabinet(message: Message, db):
    tg_id = message.from_user.id
    user = await get_user(db, tg_id)
    sub = await get_subscription(db, tg_id)

    if not user or not sub:
        await message.answer("Не нашёл ваш профиль. Нажмите /start.")
        return

    daily_limit = user["daily_limit"]
    daily_count = user["daily_count"]
    is_active = bool(user["is_active"])

    tariff = sub["tariff"]
    next_pay = _fmt_date(sub.get("next_payment_at"))

    if tariff == "free":
        limit_text = f"{daily_count} из {daily_limit}"
        await message.answer(
            "👤 <b>Ваш личный кабинет</b>\n"
            f"📦 Тариф: <b>Пробный</b> (осталось {limit_text} запросов)\n"
            f"✅ Статус: <b>{'Активен' if is_active else 'Неактивен'}</b>\n\n"
            "Чтобы оформить подписку — /pay"
        )
        return

    await message.answer(
        "👤 <b>Ваш личный кабинет</b>\n"
        f"📦 Тариф: <b>{tariff}</b>\n"
        f"🔢 Запросов сегодня: <b>{daily_count} из {daily_limit if daily_limit is not None else '∞'}</b>\n"
        f"📅 Следующая оплата: <b>{next_pay}</b>\n"
        f"✅ Статус: <b>{'Активен' if is_active else 'Неактивен'}</b>\n\n"
        "Оплата/смена тарифа — /pay\n"
        "Отписка — /cancel_sub"
    )


@router.message(Command("pay"))
async def pay_placeholder(message: Message):
    await message.answer("Оплата будет на 2-м этапе (ЮKassa). Пока это заглушка.")


@router.message(Command("cancel_sub"))
async def cancel_placeholder(message: Message):
    await message.answer("Отписка будет на 2-м этапе (ЮKassa). Пока это заглушка.")

