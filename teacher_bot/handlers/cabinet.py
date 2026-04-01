from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.queries import get_subscription, get_user, cancel_subscription
from keyboards.callbacks import TariffCb, PayConfirmCb, CancelSubCb
from keyboards.user_kb import pay_tariffs_kb, pay_confirm_change_kb, cancel_sub_confirm_kb
from services.prodamus import make_payment_url
from states import Pay, CancelSub
from tariffs import TARIFFS


router = Router()


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y")
    except Exception:
        return str(iso)


# ─── /cabinet ──────────────────────────────────────────────────────────────

@router.message(Command("cabinet"))
async def cabinet(message: Message, db):
    tg_id = message.from_user.id
    user  = await get_user(db, tg_id)
    sub   = await get_subscription(db, tg_id)

    if not user or not sub:
        await message.answer("Не нашёл ваш профиль. Нажмите /start.")
        return

    daily_limit = user["daily_limit"]
    daily_count = user["daily_count"]
    is_active   = bool(user["is_active"])
    tariff_key  = sub["tariff"]
    next_pay    = _fmt_date(sub.get("next_payment_at"))
    auto_renew  = bool(sub.get("auto_renew", 0))

    tariff = TARIFFS.get(tariff_key)
    tariff_name = tariff.name if tariff else tariff_key

    if tariff_key == "free":
        remaining = max(0, (daily_limit or 0) - daily_count)
        await message.answer(
            "👤 <b>Ваш личный кабинет</b>\n\n"
            f"📦 Тариф: <b>Пробный</b>\n"
            f"🔢 Осталось запросов: <b>{remaining} из {daily_limit}</b>\n"
            f"✅ Статус: <b>{'Активен' if is_active else 'Неактивен'}</b>\n\n"
            "Чтобы оформить подписку — /pay",
        )
        return

    limit_text = "∞" if daily_limit is None else str(daily_limit)
    renew_text = "✅ Активно" if auto_renew else "❌ Отключено (истечёт в срок)"
    await message.answer(
        "👤 <b>Ваш личный кабинет</b>\n\n"
        f"📦 Тариф: <b>{tariff_name}</b>\n"
        f"🔢 Запросов сегодня: <b>{daily_count} из {limit_text}</b>\n"
        f"📅 Следующая оплата: <b>{next_pay}</b>\n"
        f"🔄 Автопродление: {renew_text}\n"
        f"✅ Статус: <b>{'Активен' if is_active else 'Неактивен'}</b>\n\n"
        "Оплата / смена тарифа — /pay\n"
        "Отписка — /cancel_sub",
    )


# ─── /pay ──────────────────────────────────────────────────────────────────

@router.message(Command("pay"))
async def pay_start(message: Message, state: FSMContext, db):
    tg_id = message.from_user.id
    sub   = await get_subscription(db, tg_id)

    # Если уже есть активная платная подписка — предупреждаем
    if sub and sub["tariff"] != "free" and sub.get("next_payment_at"):
        tariff = TARIFFS.get(sub["tariff"])
        tariff_name = tariff.name if tariff else sub["tariff"]
        next_pay = _fmt_date(sub.get("next_payment_at"))
        await message.answer(
            f"У вас активен тариф <b>{tariff_name}</b> до <b>{next_pay}</b>.\n\n"
            "При смене тарифа новый период 30 дней начнётся с сегодняшнего дня.\n\n"
            "Выберите новый тариф:",
            reply_markup=pay_tariffs_kb(),
        )
    else:
        await message.answer(
            "Выберите тариф:",
            reply_markup=pay_tariffs_kb(),
        )
    await state.set_state(Pay.choose_tariff)


@router.callback_query(Pay.choose_tariff, TariffCb.filter())
async def pay_tariff_chosen(
    call: CallbackQuery,
    callback_data: TariffCb,
    state: FSMContext,
    db,
    prodamus_secret_key: str,
    webhook_url: str,
):
    tg_id      = call.from_user.id
    tariff_key = callback_data.key
    tariff     = TARIFFS.get(tariff_key)

    if not tariff:
        await call.answer("Неизвестный тариф.", show_alert=True)
        return

    # Сохраняем выбранный тариф в FSM на случай подтверждения смены
    await state.update_data(chosen_tariff_key=tariff_key)

    # Проверяем — уже есть активная платная подписка?
    sub = await get_subscription(db, tg_id)
    if sub and sub["tariff"] != "free" and sub.get("next_payment_at"):
        await call.message.edit_text(
            f"Сменить тариф на <b>{tariff.name}</b>?\n"
            f"💰 Стоимость: <b>{tariff.price:.0f} руб / 30 дней</b>\n\n"
            "Новый период начнётся с сегодняшнего дня.",
            reply_markup=pay_confirm_change_kb(tariff.name),
        )
        await state.set_state(Pay.confirm_change)
        return

    # Нет активной подписки — сразу генерируем ссылку
    await _send_payment_link(
        call=call,
        state=state,
        tg_id=tg_id,
        tariff_key=tariff_key,
        prodamus_secret_key=prodamus_secret_key,
        webhook_url=webhook_url,
    )


@router.callback_query(Pay.confirm_change, PayConfirmCb.filter(F.action == "yes"))
async def pay_confirm_change_yes(
    call: CallbackQuery,
    state: FSMContext,
    prodamus_secret_key: str,
    webhook_url: str,
):
    tg_id = call.from_user.id
    data  = await state.get_data()
    tariff_key = data.get("chosen_tariff_key", "basic")
    await _send_payment_link(
        call=call,
        state=state,
        tg_id=tg_id,
        tariff_key=tariff_key,
        prodamus_secret_key=prodamus_secret_key,
        webhook_url=webhook_url,
    )


@router.callback_query(Pay.confirm_change, PayConfirmCb.filter(F.action == "no"))
async def pay_confirm_change_no(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Выберите тариф:", reply_markup=pay_tariffs_kb())
    await state.set_state(Pay.choose_tariff)


async def _send_payment_link(
    *,
    call: CallbackQuery,
    state: FSMContext,
    tg_id: int,
    tariff_key: str,
    prodamus_secret_key: str,
    webhook_url: str,
) -> None:
    """Генерирует платёжную ссылку и отправляет пользователю."""
    tariff = TARIFFS[tariff_key]
    url = make_payment_url(
        webhook_url=webhook_url,
        prodamus_secret_key=prodamus_secret_key,
        tg_id=tg_id,
        tariff_key=tariff_key,
        tariff_name=tariff.name,
        price=tariff.price,
    )

    await state.clear()

    if not url:
        # Продамус не настроен — сообщаем пользователю
        await call.message.edit_text(
            "⏳ <b>Оплата временно недоступна</b>\n\n"
            "Платёжная система настраивается. Попробуйте позже или напишите администратору.",
        )
        return

    await call.message.edit_text(
        f"💳 <b>Оплата тарифа «{tariff.name}»</b>\n\n"
        f"Стоимость: <b>{tariff.price:.0f} руб / 30 дней</b>\n\n"
        f"Нажмите кнопку для оплаты:\n{url}\n\n"
        "После оплаты подписка активируется автоматически. "
        "Проверить статус — /cabinet",
    )


# ─── /cancel_sub ───────────────────────────────────────────────────────────

@router.message(Command("cancel_sub"))
async def cancel_sub_start(message: Message, state: FSMContext, db):
    tg_id = message.from_user.id
    sub   = await get_subscription(db, tg_id)

    if not sub or sub["tariff"] == "free":
        await message.answer("У вас нет активной платной подписки.")
        return

    next_pay = _fmt_date(sub.get("next_payment_at"))
    await message.answer(
        "❓ <b>Вы уверены, что хотите отписаться?</b>\n\n"
        f"✅ Тариф активен до <b>{next_pay}</b> — доступ сохраняется.\n"
        "❌ После этой даты доступ закроется, деньги не списываются.\n"
        "📁 Все данные (дети, увлечения) сохранятся.",
        reply_markup=cancel_sub_confirm_kb(),
    )
    await state.set_state(CancelSub.confirm)


@router.callback_query(CancelSub.confirm, CancelSubCb.filter(F.action == "yes"))
async def cancel_sub_confirmed(call: CallbackQuery, state: FSMContext, db):
    tg_id = call.from_user.id
    await cancel_subscription(db, tg_id)
    await state.clear()

    sub      = await get_subscription(db, tg_id)
    next_pay = _fmt_date(sub.get("next_payment_at")) if sub else "—"

    await call.message.edit_text(
        "✅ <b>Автопродление отключено.</b>\n\n"
        f"Доступ сохраняется до <b>{next_pay}</b>.\n"
        "После этой даты тариф перейдёт в Пробный.\n\n"
        "Хотите снова оформить подписку — /pay",
    )


@router.callback_query(CancelSub.confirm, CancelSubCb.filter(F.action == "no"))
async def cancel_sub_rejected(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Отписка отменена. Подписка остаётся активной.")
