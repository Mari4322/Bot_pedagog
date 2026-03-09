from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database.queries import ensure_user, set_admin
from handlers.dialog import show_step1


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, db, admin_tg_id: int):
    first = await ensure_user(db, message.from_user.id, message.from_user.username)
    if message.from_user.id == admin_tg_id:
        await set_admin(db, admin_tg_id, True)

    if first:
        await message.answer(
            "Привет! Я — педагог 🎓\n"
            "Помогу объяснить любую школьную тему через то, что нравится вашему ребёнку.\n"
            "Просто, понятно, за 5–7 минут. Давайте начнём!"
        )
    else:
        await message.answer("Рады вас снова видеть! Продолжим?")

    await show_step1(message=message, state=state, db=db)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Команды:\n"
        "/start — начать\n"
        "/cabinet — личный кабинет\n"
        "/pay — оплата (2-й этап)\n"
        "/cancel_sub — отписка (2-й этап)"
    )

