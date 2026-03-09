from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards.callbacks import AdminCb, ModelCb


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню администратора — инлайн-кнопки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Сменить модель",          callback_data=AdminCb(action="change_model").pack())],
            [InlineKeyboardButton(text="💰 Баланс polza.ai",          callback_data=AdminCb(action="balance").pack())],
            [InlineKeyboardButton(text="👥 Пользователи CSV",         callback_data=AdminCb(action="get_users").pack())],
            [InlineKeyboardButton(text="👶 Дети и увлечения CSV",     callback_data=AdminCb(action="get_children").pack())],
            [InlineKeyboardButton(text="📋 Логи запросов CSV",        callback_data=AdminCb(action="get_logs").pack())],
            [InlineKeyboardButton(text="➕ Добавить администратора",  callback_data=AdminCb(action="add_admin").pack())],
            [InlineKeyboardButton(text="➖ Удалить администратора",   callback_data=AdminCb(action="delete_admin").pack())],
        ]
    )


def models_kb(models: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура выбора нейросети."""
    rows = [
        [InlineKeyboardButton(text=m["name"], callback_data=ModelCb(model_id=m["id"]).pack())]
        for m in models
    ]
    # Кнопка «Назад» в меню администратора
    rows.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data=AdminCb(action="back_to_menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_input_cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены при вводе tg_id — возврат в меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=AdminCb(action="back_to_menu").pack())]
        ]
    )
