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
    # Игнорируем ботов — не регистрируем в базе, не отвечаем
    if message.from_user.is_bot:
        return

    first = await ensure_user(db, message.from_user.id, message.from_user.username,
                              is_bot=message.from_user.is_bot)
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
        "ℹ️ <b>Как пользоваться ботом:</b>\n\n"
        "Я помогу объяснить любую школьную тему через увлечения вашего ребёнка — "
        "просто, понятно, за 5–7 минут.\n\n"
        "<b>Доступные команды:</b>\n"
        "/start — начать / вернуться в главное меню\n"
        "/help — эта инструкция\n"
        "/cabinet — личный кабинет (тариф, лимиты, дата оплаты)\n"
        "/pay — оплатить или сменить тариф\n"
        "/cancel_sub — отменить подписку\n\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Выберите ребёнка (или добавьте нового)\n"
        "2️⃣ Укажите возраст\n"
        "3️⃣ Выберите увлечение\n"
        "4️⃣ Введите тему для объяснения\n"
        "5️⃣ Оцените уровень тревожности (1–10)\n"
        "6️⃣ Проверьте данные и нажмите «🚀 Сгенерировать»\n\n"
        "Если что-то пошло не так — просто нажмите /start."
    )

