from __future__ import annotations

"""
Хендлеры администратора.

Команды:
  /admin         — главное меню с инлайн-кнопками
  /change_model  — смена нейросети (также кнопкой из меню)
  /get_users     — выгрузка CSV пользователей
  /get_children  — выгрузка CSV детей и увлечений
  /get_logs      — выгрузка CSV логов запросов
  /add_admin     — добавить администратора (команда + кнопка)
  /delete_admin  — удалить администратора (команда + кнопка)

Кнопочное меню:
  Нажатие на кнопку в /admin делает то же самое, что и команда напрямую.
  Для /add_admin и /delete_admin кнопка переводит в FSM-состояние ввода tg_id.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from database.queries import get_user, set_admin, set_setting
from keyboards.admin_kb import admin_input_cancel_kb, admin_menu_kb, models_kb
from keyboards.callbacks import AdminCb, ModelCb
from services.balance_service import get_balance
from states import Admin
from utils.exports import export_children, export_logs, export_users

router = Router()
_log = logging.getLogger("admin")


# ─── Список доступных нейросетей ───────────────────────────────────────────

AVAILABLE_MODELS = [
    {"id": "openai/gpt-4o",                "name": "GPT-4o"},
    {"id": "openai/gpt-4.1",               "name": "GPT-4.1"},
    {"id": "anthropic/claude-3.7-sonnet",  "name": "Claude 3.7 Sonnet"},
    {"id": "anthropic/claude-sonnet-4.5",  "name": "Claude Sonnet 4.5"},
    {"id": "google/gemini-2.5-pro",        "name": "Gemini 2.5 Pro"},
    {"id": "google/gemini-2.5-flash",      "name": "Gemini 2.5 Flash"},
    {"id": "deepseek/deepseek-r1",         "name": "DeepSeek R1"},
    {"id": "x-ai/grok-3",                  "name": "Grok-3"},
    {"id": "z-ai/glm-4.5",                 "name": "GLM-4.5"},
]


# ─── FSM-состояния для ввода tg_id ─────────────────────────────────────────

class AdminInput(StatesGroup):
    waiting_add_admin_id    = State()   # ждём tg_id для добавления
    waiting_delete_admin_id = State()   # ждём tg_id для удаления


# ─── Вспомогательные функции проверки прав ─────────────────────────────────

async def _require_admin(message: Message, db) -> bool:
    """Проверяет, является ли отправитель сообщения администратором."""
    u = await get_user(db, message.from_user.id)
    if not u or not bool(u["is_admin"]):
        return False
    return True


async def _require_admin_call(call: CallbackQuery, db) -> bool:
    """Проверяет, является ли нажавший кнопку администратором."""
    u = await get_user(db, call.from_user.id)
    if not u or not bool(u["is_admin"]):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return False
    return True


# ─── Текст главного меню ───────────────────────────────────────────────────

_ADMIN_MENU_TEXT = (
    "🛠 <b>Панель администратора</b>\n\n"
    "Выберите действие:"
)


# ─── /admin — главное меню ─────────────────────────────────────────────────

@router.message(Command("admin"))
async def admin_menu(message: Message, db, state: FSMContext):
    if not await _require_admin(message, db):
        return
    await state.clear()
    await message.answer(_ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())


# ─── Кнопка «Назад в меню» (из любого подменю) ─────────────────────────────

@router.callback_query(AdminCb.filter(F.action == "back_to_menu"))
async def admin_back_to_menu(call: CallbackQuery, db, state: FSMContext):
    if not await _require_admin_call(call, db):
        return
    await state.clear()
    await call.message.edit_text(_ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())


# ─── Смена модели (/change_model и кнопка) ─────────────────────────────────

@router.message(Command("change_model"))
async def change_model_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    await message.answer("🔧 Выберите нейросеть:", reply_markup=models_kb(AVAILABLE_MODELS))


@router.callback_query(AdminCb.filter(F.action == "change_model"))
async def change_model_btn(call: CallbackQuery, db):
    if not await _require_admin_call(call, db):
        return
    await call.message.edit_text("🔧 Выберите нейросеть:", reply_markup=models_kb(AVAILABLE_MODELS))


@router.callback_query(AdminCb.filter(F.action == "edit_prompt"))
async def edit_prompt_btn(call: CallbackQuery, db):
    """Кнопка 'Редактировать промпт' из меню — показывает текущий промпт."""
    if not await _require_admin_call(call, db):
        return
    
    # Читаем текущий промпт
    from pathlib import Path
    prompt_path = Path(__file__).resolve().parent.parent / "prompt.txt"
    try:
        current_prompt = prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        _log.error("Не удалось прочитать prompt.txt: %s", e)
        await call.answer("❌ Ошибка чтения файла prompt.txt", show_alert=True)
        return

    # Показываем промпт (обрезаем если слишком длинный)
    preview = current_prompt[:4000] + ("..." if len(current_prompt) > 4000 else "")
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить промпт", callback_data="admin_edit_prompt")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_back_menu")],
    ])

    await call.message.edit_text(
        f"📝 <b>Текущий системный промпт:</b>\n\n"
        f"<code>{preview}</code>\n\n"
        f"Символов: {len(current_prompt)}",
        reply_markup=kb,
    )


@router.callback_query(ModelCb.filter())
async def model_pick(call: CallbackQuery, callback_data: ModelCb, db):
    if not await _require_admin_call(call, db):
        return
    await set_setting(db, "current_model", callback_data.model_id)
    _log.info("Админ %s сменил модель на %s", call.from_user.id, callback_data.model_id)
    await call.message.edit_text(
        f"✅ Готово. Текущая модель: <b>{callback_data.model_id}</b>\n\n"
        f"{_ADMIN_MENU_TEXT}",
        reply_markup=admin_menu_kb(),
    )


# ─── Выгрузка CSV (/get_users, /get_children, /get_logs и кнопки) ──────────

@router.message(Command("get_users"))
async def get_users_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    filename, content = await export_users(db)
    await message.answer_document(BufferedInputFile(content, filename=filename),
                                  caption="👥 Список пользователей")


@router.callback_query(AdminCb.filter(F.action == "get_users"))
async def get_users_btn(call: CallbackQuery, db):
    if not await _require_admin_call(call, db):
        return
    await call.answer()
    filename, content = await export_users(db)
    await call.message.answer_document(BufferedInputFile(content, filename=filename),
                                       caption="👥 Список пользователей")


@router.message(Command("get_children"))
async def get_children_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    filename, content = await export_children(db)
    await message.answer_document(BufferedInputFile(content, filename=filename),
                                  caption="👶 Дети и увлечения")


@router.callback_query(AdminCb.filter(F.action == "get_children"))
async def get_children_btn(call: CallbackQuery, db):
    if not await _require_admin_call(call, db):
        return
    await call.answer()
    filename, content = await export_children(db)
    await call.message.answer_document(BufferedInputFile(content, filename=filename),
                                       caption="👶 Дети и увлечения")


@router.message(Command("get_logs"))
async def get_logs_cmd(message: Message, db):
    if not await _require_admin(message, db):
        return
    filename, content = await export_logs(db)
    await message.answer_document(BufferedInputFile(content, filename=filename),
                                  caption="📋 Логи запросов")


@router.callback_query(AdminCb.filter(F.action == "get_logs"))
async def get_logs_btn(call: CallbackQuery, db):
    if not await _require_admin_call(call, db):
        return
    await call.answer()
    filename, content = await export_logs(db)
    await call.message.answer_document(BufferedInputFile(content, filename=filename),
                                       caption="📋 Логи запросов")


# ─── Баланс polza.ai (/balance и кнопка) ───────────────────────────────────

async def _format_balance_text(polza_api_key: str, balance_threshold: float) -> str:
    """Запрашивает баланс и возвращает готовый текст для отправки."""
    try:
        balance = await get_balance(polza_api_key)
        if balance < balance_threshold:
            status = f"⚠️ <b>Ниже порога!</b> (порог: {balance_threshold:.0f} руб.)"
        else:
            status = f"✅ В норме (порог: {balance_threshold:.0f} руб.)"
        return (
            f"💰 <b>Баланс polza.ai</b>\n\n"
            f"Текущий баланс: <b>{balance:.2f} руб.</b>\n"
            f"Статус: {status}"
        )
    except RuntimeError as e:
        return f"❗ <b>Не удалось получить баланс</b>\n\n{e}"


@router.message(Command("balance"))
async def balance_cmd(message: Message, db, polza_api_key: str, balance_threshold: float):
    if not await _require_admin(message, db):
        return
    text = await _format_balance_text(polza_api_key, balance_threshold)
    await message.answer(text, reply_markup=admin_menu_kb())


@router.callback_query(AdminCb.filter(F.action == "balance"))
async def balance_btn(call: CallbackQuery, db, polza_api_key: str, balance_threshold: float):
    if not await _require_admin_call(call, db):
        return
    await call.answer()
    text = await _format_balance_text(polza_api_key, balance_threshold)
    await call.message.edit_text(text, reply_markup=admin_menu_kb())


# ─── Добавление администратора (/add_admin и кнопка) ───────────────────────

@router.message(Command("add_admin"))
async def add_admin_cmd(message: Message, db):
    """
    Использование: /add_admin <tg_id>
    Если tg_id не передан — просим ввести в ответном сообщении.
    """
    if not await _require_admin(message, db):
        return
    parts = (message.text or "").split()
    if len(parts) == 2 and parts[1].lstrip("-").isdigit():
        tg_id = int(parts[1])
        await set_admin(db, tg_id, True)
        _log.info("Админ %s добавил нового админа %s", message.from_user.id, tg_id)
        await message.answer(f"✅ Пользователь <b>{tg_id}</b> теперь администратор.")
    else:
        await message.answer(
            "Введите Telegram ID пользователя, которого хотите сделать администратором:",
            reply_markup=admin_input_cancel_kb(),
        )
        # Запоминаем tg_id запросившего, чтобы FSM знал чей это ввод
        # (state здесь не передаётся — используем отдельный хендлер без FSM)
        await message.answer("⚠️ Или отправьте: /add_admin <tg_id>")


@router.callback_query(AdminCb.filter(F.action == "add_admin"))
async def add_admin_btn(call: CallbackQuery, db, state: FSMContext):
    if not await _require_admin_call(call, db):
        return
    await call.message.edit_text(
        "➕ <b>Добавление администратора</b>\n\n"
        "Введите Telegram ID пользователя:",
        reply_markup=admin_input_cancel_kb(),
    )
    await state.set_state(AdminInput.waiting_add_admin_id)


@router.message(AdminInput.waiting_add_admin_id)
async def add_admin_input(message: Message, state: FSMContext, db):
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "❌ Неверный формат. Введите числовой Telegram ID:",
            reply_markup=admin_input_cancel_kb(),
        )
        return
    tg_id = int(raw)
    await set_admin(db, tg_id, True)
    _log.info("Админ %s добавил нового админа %s (через FSM)", message.from_user.id, tg_id)
    await state.clear()
    await message.answer(
        f"✅ Пользователь <b>{tg_id}</b> теперь администратор.\n\n{_ADMIN_MENU_TEXT}",
        reply_markup=admin_menu_kb(),
    )


# ─── Удаление администратора (/delete_admin и кнопка) ──────────────────────

@router.message(Command("delete_admin"))
async def delete_admin_cmd(message: Message, db):
    """
    Использование: /delete_admin <tg_id>
    Если tg_id не передан — просим ввести.
    Нельзя снять права с самого себя.
    """
    if not await _require_admin(message, db):
        return
    parts = (message.text or "").split()
    if len(parts) == 2 and parts[1].lstrip("-").isdigit():
        tg_id = int(parts[1])
        if tg_id == message.from_user.id:
            await message.answer("⚠️ Нельзя снять права администратора с самого себя.")
            return
        await set_admin(db, tg_id, False)
        _log.info("Админ %s снял права у %s", message.from_user.id, tg_id)
        await message.answer(f"✅ Пользователь <b>{tg_id}</b> больше не администратор.")
    else:
        await message.answer("⚠️ Используйте: /delete_admin <tg_id>")


@router.callback_query(AdminCb.filter(F.action == "delete_admin"))
async def delete_admin_btn(call: CallbackQuery, db, state: FSMContext):
    if not await _require_admin_call(call, db):
        return
    await call.message.edit_text(
        "➖ <b>Удаление администратора</b>\n\n"
        "Введите Telegram ID пользователя, которого хотите лишить прав:",
        reply_markup=admin_input_cancel_kb(),
    )
    await state.set_state(AdminInput.waiting_delete_admin_id)


@router.message(AdminInput.waiting_delete_admin_id)
async def delete_admin_input(message: Message, state: FSMContext, db):
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "❌ Неверный формат. Введите числовой Telegram ID:",
            reply_markup=admin_input_cancel_kb(),
        )
        return
    tg_id = int(raw)
    if tg_id == message.from_user.id:
        await message.answer(
            "⚠️ Нельзя снять права с самого себя.\n\nВведите другой ID:",
            reply_markup=admin_input_cancel_kb(),
        )
        return
    await set_admin(db, tg_id, False)
    _log.info("Админ %s снял права у %s (через FSM)", message.from_user.id, tg_id)
    await state.clear()
    await message.answer(
        f"✅ Пользователь <b>{tg_id}</b> больше не администратор.\n\n{_ADMIN_MENU_TEXT}",
        reply_markup=admin_menu_kb(),
    )


# ─── /prompt — редактирование системного промпта ────────────────────────────

@router.message(Command("prompt"))
async def cmd_prompt(message: Message, state: FSMContext, db, admin_tg_id: int):
    """Показывает текущий промпт и предлагает изменить."""
    user = await get_user(db, message.from_user.id)
    if not user or not user["is_admin"]:
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return

    # Читаем текущий промпт
    from pathlib import Path
    prompt_path = Path(__file__).resolve().parent.parent / "prompt.txt"
    try:
        current_prompt = prompt_path.read_text(encoding="utf-8")
    except Exception as e:
        _log.error("Не удалось прочитать prompt.txt: %s", e)
        await message.answer("❌ Ошибка чтения файла prompt.txt")
        return

    # Показываем промпт (обрезаем если слишком длинный для одного сообщения)
    preview = current_prompt[:4000] + ("..." if len(current_prompt) > 4000 else "")
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить промпт", callback_data="admin_edit_prompt")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_back_menu")],
    ])

    await message.answer(
        f"📝 <b>Текущий системный промпт:</b>\n\n"
        f"<code>{preview}</code>\n\n"
        f"Символов: {len(current_prompt)}",
        reply_markup=kb,
    )


@router.callback_query(F.data == "admin_edit_prompt")
async def admin_edit_prompt_start(call: CallbackQuery, state: FSMContext):
    """Кнопка 'Изменить промпт' — переводит в состояние ввода."""
    from states import Admin
    await state.set_state(Admin.edit_prompt)
    await call.message.edit_text(
        "✏️ <b>Редактирование промпта</b>\n\n"
        "Отправьте новый текст промпта одним сообщением.\n\n"
        "Для отмены нажмите /cancel",
    )


@router.message(Admin.edit_prompt)
async def admin_edit_prompt_save(message: Message, state: FSMContext, db):
    """Сохраняет новый промпт в prompt.txt."""
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer(
            f"❌ Изменение промпта отменено.\n\n{_ADMIN_MENU_TEXT}",
            reply_markup=admin_menu_kb(),
        )
        return

    new_prompt = message.text or ""
    if len(new_prompt) < 50:
        await message.answer(
            "⚠️ Промпт слишком короткий (минимум 50 символов).\n\n"
            "Попробуйте ещё раз или /cancel для отмены."
        )
        return

    # Сохраняем промпт
    from pathlib import Path
    prompt_path = Path(__file__).resolve().parent.parent / "prompt.txt"
    try:
        prompt_path.write_text(new_prompt, encoding="utf-8")
        _log.info("Админ %s обновил prompt.txt (%d символов)", message.from_user.id, len(new_prompt))
    except Exception as e:
        _log.error("Ошибка записи prompt.txt: %s", e)
        await message.answer("❌ Не удалось сохранить промпт. Ошибка записи файла.")
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ <b>Промпт успешно обновлён!</b>\n\n"
        f"Новый размер: {len(new_prompt)} символов\n\n"
        f"Изменения вступят в силу при следующей генерации.\n\n"
        f"{_ADMIN_MENU_TEXT}",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == "admin_back_menu")
async def admin_back_to_menu(call: CallbackQuery):
    """Возврат в админ-меню."""
    await call.message.edit_text(_ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())

