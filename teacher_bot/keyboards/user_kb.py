from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards.callbacks import AnxietyCb, ChildCb, HobbyCb, NavCb, SimpleCb
from keyboards.callbacks import TariffCb, PayConfirmCb, CancelSubCb
from tariffs import PAID_TARIFFS


def step1_children_kb(children: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in children:
        rows.append(
            [
                InlineKeyboardButton(text=str(c["name"]), callback_data=ChildCb(action="select", child_id=c["id"]).pack()),
                InlineKeyboardButton(text="🖊 Редактировать", callback_data=ChildCb(action="edit", child_id=c["id"]).pack()),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить ребёнка", callback_data=SimpleCb(action="add_child").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def step2_age_kb(age: int | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if age is not None:
        rows.append([InlineKeyboardButton(text=f"✅ Подтвердить ({age} лет)", callback_data=SimpleCb(action="confirm_age").pack())])
        rows.append([InlineKeyboardButton(text="🖊 Изменить возраст", callback_data=SimpleCb(action="change_age").pack())])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="step1").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def step3_hobbies_kb(hobbies: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for h in hobbies:
        rows.append(
            [
                InlineKeyboardButton(text=str(h["hobby"]), callback_data=HobbyCb(action="select", hobby_id=h["id"]).pack()),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=HobbyCb(action="del", hobby_id=h["id"]).pack()),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить увлечение", callback_data=SimpleCb(action="add_hobby").pack())])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="step2").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(to: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to=to).pack())]]
    )


def anxiety_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(text=str(i), callback_data=AnxietyCb(value=i).pack()) for i in range(1, 6)])
    rows.append([InlineKeyboardButton(text=str(i), callback_data=AnxietyCb(value=i).pack()) for i in range(6, 11)])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="step4").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сгенерировать", callback_data=SimpleCb(action="generate").pack())],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="step5").pack())],
        ]
    )


def after_answer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=SimpleCb(action="regen").pack())],
            [InlineKeyboardButton(text="🆕 Новый запрос", callback_data=SimpleCb(action="new").pack())],
        ]
    )


def regen_pick_hobby_kb(hobbies: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=str(h["hobby"]), callback_data=HobbyCb(action="select", hobby_id=h["id"]).pack())]
        for h in hobbies
    ]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="regen_back").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def regen_comment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data=SimpleCb(action="skip_comment").pack())],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="regen_hobby_back").pack())],
        ]
    )


def regen_comment_confirm_kb() -> InlineKeyboardMarkup:
    """Клавиатура после ввода комментария — Далее или Назад к выбору хобби."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Далее", callback_data=SimpleCb(action="comment_next").pack())],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="regen_hobby_back").pack())],
        ]
    )


def regen_summary_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сгенерировать", callback_data=SimpleCb(action="regen_generate").pack())],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=NavCb(to="regen_comment_back").pack())],
        ]
    )


# ─── /pay — выбор тарифа ───────────────────────────────────────────────────

def pay_tariffs_kb() -> InlineKeyboardMarkup:
    """Кнопки платных тарифов для /pay."""
    rows = [
        [InlineKeyboardButton(
            text=f"📦 {t.name} — {t.description}",
            callback_data=TariffCb(key=t.key).pack(),
        )]
        for t in PAID_TARIFFS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pay_confirm_change_kb(tariff_name: str) -> InlineKeyboardMarkup:
    """Подтверждение смены тарифа (если подписка уже активна)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"✅ Да, сменить на «{tariff_name}»",
                callback_data=PayConfirmCb(action="yes").pack(),
            )],
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=PayConfirmCb(action="no").pack(),
            )],
        ]
    )


# ─── /cancel_sub — подтверждение отписки ───────────────────────────────────

def cancel_sub_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Да, отписаться",
                callback_data=CancelSubCb(action="yes").pack(),
            )],
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=CancelSubCb(action="no").pack(),
            )],
        ]
    )

