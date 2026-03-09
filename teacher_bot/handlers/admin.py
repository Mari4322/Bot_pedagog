from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from database.queries import get_user, set_admin, set_setting
from keyboards.admin_kb import models_kb
from keyboards.callbacks import ModelCb
from utils.exports import export_children, export_logs, export_users


router = Router()


AVAILABLE_MODELS = [
    {"id": "openai/gpt-4o", "name": "GPT-4o"},
    {"id": "openai/gpt-4.1", "name": "GPT-4.1"},
    {"id": "anthropic/claude-3.7-sonnet", "name": "Claude 3.7 Sonnet"},
    {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5"},
    {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
    {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1"},
    {"id": "x-ai/grok-3", "name": "Grok-3"},
    {"id": "z-ai/glm-4.5", "name": "GLM-4.5"},
]


async def _require_admin(message: Message, db) -> bool:
    u = await get_user(db, message.from_user.id)
    if not u or not bool(u["is_admin"]):
        return False
    return True


async def _require_admin_call(call: CallbackQuery, db) -> bool:
    u = await get_user(db, call.from_user.id)
    if not u or not bool(u["is_admin"]):
        await call.answer("Нет доступа", show_alert=True)
        return False
    return True


@router.message(Command("admin"))
async def admin_menu(message: Message, db):
    if not await _require_admin(message, db):
        return
    await message.answer(
        "Админ-команды:\n"
        "/change_model — смена модели\n"
        "/get_users — выгрузка пользователей CSV\n"
        "/get_children — выгрузка детей и увлечений CSV\n"
        "/get_logs — выгрузка логов CSV\n"
        "/add_admin <tg_id> — добавить администратора"
    )


@router.message(Command("change_model"))
async def change_model(message: Message, db):
    if not await _require_admin(message, db):
        return
    await message.answer("Выберите модель:", reply_markup=models_kb(AVAILABLE_MODELS))


@router.callback_query(ModelCb.filter())
async def model_pick(call: CallbackQuery, callback_data: ModelCb, db):
    if not await _require_admin_call(call, db):
        return
    await set_setting(db, "current_model", callback_data.model_id)
    await call.message.edit_text(f"Готово. Текущая модель: <b>{callback_data.model_id}</b>")


@router.message(Command("get_users"))
async def get_users_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    filename, content = await export_users(db)
    await message.answer_document(BufferedInputFile(content, filename=filename))


@router.message(Command("get_children"))
async def get_children_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    filename, content = await export_children(db)
    await message.answer_document(BufferedInputFile(content, filename=filename))


@router.message(Command("get_logs"))
async def get_logs_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    filename, content = await export_logs(db)
    await message.answer_document(BufferedInputFile(content, filename=filename))


@router.message(Command("add_admin"))
async def add_admin_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /add_admin <tg_id>")
        return
    tg_id = int(parts[1])
    await set_admin(db, tg_id, True)
    await message.answer(f"Готово. Пользователь {tg_id} теперь админ.")

