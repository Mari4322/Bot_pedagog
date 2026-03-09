from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards.callbacks import ModelCb


def models_kb(models: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=m["name"], callback_data=ModelCb(model_id=m["id"]).pack())]
        for m in models
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

