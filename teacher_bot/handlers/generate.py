from __future__ import annotations

"""
Хендлеры генерации и перегенерации (Шаги 7–8 по ТЗ).

Ключевые правила:
- Счётчик daily_count увеличивается ТОЛЬКО при успешном ответе ИИ.
- При ЛЮБОЙ ошибке API счётчик НЕ увеличивается.
- Обработка ошибок строго по ТЗ:
    401 → лог + уведомление админу
    402 → лог + уведомление админу
    408 → сообщение пользователю «Превышено время ожидания»
    429 → повтор уже сделан в ai_service.py; сюда попадает только если попытки исчерпаны
    500 → лог + сообщение пользователю
    502/503 → повтор уже сделан в ai_service.py; сюда попадает только если попытки исчерпаны
"""

import logging
import sys
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from openai import APIConnectionError, APIStatusError, RateLimitError

from database import queries as q
from keyboards.callbacks import HobbyCb, NavCb, SimpleCb
from keyboards.user_kb import after_answer_kb, regen_comment_kb, regen_pick_hobby_kb, regen_summary_kb
from services.ai_service import AIResult, ServerAPIError, TimeoutAPIError, generate_response
from states import Dialog


# ─── Логгер ────────────────────────────────────────────────────────────────
_log = logging.getLogger("generate")
if not _log.handlers:
    _log.setLevel(logging.DEBUG)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _h_console = logging.StreamHandler(sys.stderr)
    _h_console.setFormatter(_fmt)
    _log.addHandler(_h_console)
    _log_path = Path(__file__).resolve().parent.parent / "bot_errors.log"
    try:
        _h_file = logging.FileHandler(_log_path, encoding="utf-8")
        _h_file.setFormatter(_fmt)
        _log.addHandler(_h_file)
    except Exception:
        pass


router = Router()


# ─── Вспомогательные функции ───────────────────────────────────────────────

async def _send_limit_message(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "Вы исчерпали лимит запросов на сегодня. Возвращайтесь завтра или обновите тариф — /pay"
    )


async def _notify_admin(call: CallbackQuery, admin_tg_id: int, text: str) -> None:
    """Тихо отправляем уведомление администратору, не падаем если не вышло."""
    try:
        await call.bot.send_message(admin_tg_id, text)
    except Exception as notify_err:
        _log.warning("Не удалось уведомить админа %d: %s", admin_tg_id, notify_err)


# ─── Основная функция генерации ─────────────────────────────────────────────

async def _do_generate(
    *,
    call: CallbackQuery,
    state: FSMContext,
    db,
    ai_client,
    admin_tg_id: int,
    comment: str | None = None,
    override_hobby: str | None = None,
) -> None:
    tg_id = call.from_user.id

    # Боты не могут делать запросы к нейросети — молча игнорируем
    if call.from_user.is_bot:
        _log.warning("Попытка запроса к ИИ от бота tg_id=%d username=%s — отклонено",
                     tg_id, call.from_user.username)
        await call.answer("Боты не могут использовать этот бот.", show_alert=True)
        return

    # Проверяем лимит до запроса к ИИ
    access = await q.get_access_state(db, tg_id)
    if not access.can_generate:
        await _send_limit_message(call)
        return

    # Получаем данные текущего диалога
    data = await state.get_data()
    child = await q.get_child(db, data.get("child_id"), tg_id)
    if not child or child.get("age") is None:
        await call.message.edit_text("Не нашёл данные ребёнка. Нажмите /start.")
        await state.clear()
        return

    hobby    = override_hobby or data.get("hobby_text")
    topic    = data.get("topic")
    anxiety  = data.get("anxiety")
    if not (hobby and topic and anxiety):
        await call.message.edit_text("Не хватает данных для генерации. Нажмите /start.")
        await state.clear()
        return

    model         = await q.get_setting(db, "current_model") or "openai/gpt-4o"
    FALLBACK_MODEL = "openai/gpt-4o"

    await call.message.edit_text("Готовлю объяснение, подождите... ⏳")

    # ── Попытка с текущей моделью ─────────────────────────────────────────
    result: AIResult | None = None
    try:
        result = await generate_response(
            client=ai_client,
            model=model,
            child_name=child["name"],
            child_age=int(child["age"]),
            hobby=hobby,
            topic=topic,
            anxiety_level=int(anxiety),
            comment=comment,
        )

    # ── 408 — таймаут ─────────────────────────────────────────────────────
    except TimeoutAPIError:
        _log.warning("408 Timeout при генерации для tg_id=%d", tg_id)
        # Счётчик НЕ увеличивается
        await call.message.edit_text(
            "⏱ Превышено время ожидания. Попробуйте ещё раз."
        )
        return

    # ── 500 — ошибка сервера ──────────────────────────────────────────────
    except ServerAPIError as e:
        _log.error("500 Server error для tg_id=%d: %s", tg_id, e.message)
        # Счётчик НЕ увеличивается
        await _notify_admin(call, admin_tg_id,
                            f"⚠️ polza.ai ошибка 500 (tg_id={tg_id}): {e.message}")
        await call.message.edit_text(
            "🚫 Ошибка на стороне сервиса ИИ. Уже разбираемся. Попробуйте чуть позже."
        )
        return

    # ── APIStatusError: 400 (модель не найдена) → fallback; 401/402 → уведомление ─
    except APIStatusError as e:
        code = e.status_code
        _log.error("APIStatusError %d для tg_id=%d: %s", code, tg_id, e.message)

        # Модель не найдена — переключаем на fallback и пробуем один раз
        if code == 400 and (
            "не найдена" in (e.message or "")
            or "not found" in (e.message or "").lower()
        ):
            if model != FALLBACK_MODEL:
                await q.set_setting(db, "current_model", FALLBACK_MODEL)
                _log.info("Переключили current_model %s → %s", model, FALLBACK_MODEL)
                try:
                    result = await generate_response(
                        client=ai_client,
                        model=FALLBACK_MODEL,
                        child_name=child["name"],
                        child_age=int(child["age"]),
                        hobby=hobby,
                        topic=topic,
                        anxiety_level=int(anxiety),
                        comment=comment,
                    )
                    # Успех после fallback — сохраняем и показываем
                    await _save_and_show(
                        call=call, state=state, db=db,
                        tg_id=tg_id, child=child,
                        hobby=hobby, comment=comment,
                        topic=topic, anxiety=anxiety,
                        result=result,
                    )
                    return
                except TimeoutAPIError:
                    await call.message.edit_text("⏱ Превышено время ожидания. Попробуйте ещё раз.")
                    return
                except ServerAPIError as se:
                    _log.error("500 при fallback для tg_id=%d: %s", tg_id, se.message)
                    await _notify_admin(call, admin_tg_id,
                                        f"⚠️ polza.ai 500 (fallback, tg_id={tg_id}): {se.message}")
                    await call.message.edit_text(
                        "🚫 Ошибка на стороне сервиса ИИ. Попробуйте чуть позже."
                    )
                    return
                except Exception as retry_e:
                    _log.exception("Fallback тоже упал для tg_id=%d: %s", tg_id, retry_e)
                    await call.message.edit_text(
                        "Выбранная модель недоступна в сервисе. Админ: смените модель через /change_model."
                    )
                    return
            else:
                await call.message.edit_text(
                    "Модель недоступна. Админ: смените модель через /change_model."
                )
                return

        # 401 — неверный API-ключ
        if code == 401:
            _log.error("401 Unauthorized для tg_id=%d", tg_id)
            await _notify_admin(call, admin_tg_id,
                                f"🔑 polza.ai ошибка 401 (неверный API-ключ). tg_id={tg_id}")
            await call.message.edit_text(
                "⛔ Ошибка аутентификации сервиса ИИ. Администратор уже уведомлён."
            )
            return

        # 402 — нет средств
        if code == 402:
            _log.error("402 Payment Required для tg_id=%d", tg_id)
            await _notify_admin(call, admin_tg_id,
                                f"💳 polza.ai ошибка 402 (недостаточно средств). tg_id={tg_id}")
            await call.message.edit_text(
                "💳 Сервис ИИ временно недоступен. Администратор уже уведомлён."
            )
            return

        # 403 — доступ запрещён
        if code == 403:
            _log.error("403 Forbidden для tg_id=%d", tg_id)
            await _notify_admin(call, admin_tg_id,
                                f"🚫 polza.ai ошибка 403 (доступ запрещён). tg_id={tg_id}")
            await call.message.edit_text("🚫 Доступ к сервису ИИ запрещён. Попробуйте позже.")
            return

        # 429 — исчерпаны повторные попытки (retry уже сделан в ai_service.py)
        if code == 429:
            _log.warning("429 Rate limit исчерпан для tg_id=%d", tg_id)
            await call.message.edit_text(
                "⏳ Сервис перегружен. Попробуйте ещё раз через несколько минут."
            )
            return

        # 502 / 503 — исчерпаны повторные попытки
        if code in (502, 503):
            _log.warning("%d Unavailable исчерпан для tg_id=%d", code, tg_id)
            await call.message.edit_text(
                "🔧 Сервис ИИ временно недоступен. Попробуйте позже."
            )
            return

        # Прочие коды
        await call.message.edit_text("❌ Ошибка при обращении к ИИ. Попробуйте позже.")
        return

    # ── 429 (RateLimitError) — все retry исчерпаны ───────────────────────
    except RateLimitError as e:
        _log.error("RateLimitError (все попытки исчерпаны) для tg_id=%d: %s", tg_id, e)
        await call.message.edit_text(
            "⏳ Сервис перегружен. Попробуйте ещё раз через несколько минут."
        )
        return

    # ── Проблемы соединения ───────────────────────────────────────────────
    except APIConnectionError as e:
        _log.error("APIConnectionError (все попытки исчерпаны) для tg_id=%d: %s", tg_id, e)
        await call.message.edit_text(
            "🌐 Не удалось подключиться к сервису ИИ. Проверьте позже."
        )
        return

    # ── Всё прочее ────────────────────────────────────────────────────────
    except Exception as e:
        _log.exception("Неожиданная ошибка генерации для tg_id=%d: %s: %s",
                       tg_id, type(e).__name__, e)
        await _notify_admin(call, admin_tg_id,
                            f"❗ Неожиданная ошибка генерации (tg_id={tg_id}): {type(e).__name__}: {e}")
        await call.message.edit_text("❌ Ошибка при обращении к ИИ. Попробуйте позже.")
        return

    # ── Успех: сохраняем лог, увеличиваем счётчик, показываем ответ ──────
    await _save_and_show(
        call=call, state=state, db=db,
        tg_id=tg_id, child=child,
        hobby=hobby, comment=comment,
        topic=topic, anxiety=anxiety,
        result=result,
    )


async def _save_and_show(
    *,
    call: CallbackQuery,
    state: FSMContext,
    db,
    tg_id: int,
    child: dict,
    hobby: str,
    comment: str | None,
    topic: str,
    anxiety,
    result: AIResult,
) -> None:
    """Увеличивает счётчик, пишет в лог, показывает ответ пользователю."""
    await q.increment_daily_count(db, tg_id)
    await q.log_request(
        db,
        tg_id=tg_id,
        child_name=child["name"],
        child_age=child["age"],
        hobby_used=(hobby + (f" | {comment}" if comment else "")),
        topic=topic,
        anxiety_level=int(anxiety),
        response_text=result.text,
        tokens_used=result.tokens_used,
        cost=result.cost_rub,
        model_used=result.model_used,
    )
    if result.cost_rub is not None:
        await q.add_subscription_cost(db, tg_id, float(result.cost_rub))

    await state.update_data(last_ai_text=result.text)
    await call.message.edit_text(result.text, reply_markup=after_answer_kb())


# ─── Хендлеры кнопок ───────────────────────────────────────────────────────

@router.callback_query(SimpleCb.filter(F.action == "generate"))
async def generate_from_summary(call: CallbackQuery, state: FSMContext, db, ai_client, admin_tg_id: int):
    await _do_generate(call=call, state=state, db=db, ai_client=ai_client, admin_tg_id=admin_tg_id)


@router.callback_query(SimpleCb.filter(F.action == "new"))
async def new_request(call: CallbackQuery, state: FSMContext, db):
    from handlers.dialog import show_step1
    await state.clear()
    await show_step1(call=call, state=state, db=db)


# ─── Перегенерация ─────────────────────────────────────────────────────────

@router.callback_query(SimpleCb.filter(F.action == "regen"))
async def regen_start(call: CallbackQuery, state: FSMContext, db):
    tg_id = call.from_user.id
    data = await state.get_data()
    child_id = data.get("child_id")
    child = await q.get_child(db, child_id, tg_id)
    if not child:
        from handlers.dialog import show_step1
        await show_step1(call=call, state=state, db=db)
        return

    hobbies = await q.list_hobbies(db, child_id, tg_id)
    await call.message.edit_text(
        "Выберите увлечение для нового объяснения:",
        reply_markup=regen_pick_hobby_kb(hobbies),
    )
    await state.set_state(Dialog.regen_pick_hobby)


@router.callback_query(Dialog.regen_pick_hobby, HobbyCb.filter(F.action == "select"))
async def regen_pick_hobby(call: CallbackQuery, callback_data: HobbyCb, state: FSMContext, db):
    tg_id = call.from_user.id
    data = await state.get_data()
    hobbies = await q.list_hobbies(db, data.get("child_id"), tg_id)
    chosen = next((h for h in hobbies if h["id"] == callback_data.hobby_id), None)
    if not chosen:
        await call.answer()
        return

    await state.update_data(regen_hobby_text=chosen["hobby"])
    await call.message.edit_text(
        "Хотите добавить комментарий?\n"
        "Например: \"другой пример\", \"объяснить проще\", \"через голы и статистику\"",
        reply_markup=regen_comment_kb(),
    )
    await state.set_state(Dialog.regen_comment)


@router.callback_query(Dialog.regen_comment, SimpleCb.filter(F.action == "skip_comment"))
async def regen_skip_comment(call: CallbackQuery, state: FSMContext, db):
    await state.update_data(regen_comment=None)
    await _show_regen_summary(call=call, state=state, db=db)


@router.message(Dialog.regen_comment)
async def regen_comment_input(message: Message, state: FSMContext, db):
    comment = (message.text or "").strip()
    if len(comment) > 300:
        await message.answer(
            "Слишком длинно. Введите короче или нажмите «Пропустить».",
            reply_markup=regen_comment_kb(),
        )
        return
    await state.update_data(regen_comment=comment if comment else None)

    tg_id = message.from_user.id
    data = await state.get_data()
    child = await q.get_child(db, data.get("child_id"), tg_id)
    if not child:
        await message.answer("Не нашёл ребёнка. Нажмите /start.")
        await state.clear()
        return

    hobby   = data.get("regen_hobby_text")
    topic   = data.get("topic")
    anxiety = data.get("anxiety")

    text = (
        f"👦 <b>{child['name']}, {child['age']} лет</b>\n"
        f"🎯 Увлечение: <b>{hobby}</b>\n"
        f"📚 Тема: <b>{topic}</b>\n"
        f"😟 Тревожность: <b>{anxiety} из 10</b>"
    )
    if comment:
        text += f"\n💬 Комментарий: <b>«{comment}»</b>"

    await message.answer(text, reply_markup=regen_summary_kb())
    await state.set_state(Dialog.regen_summary)


async def _show_regen_summary(*, call: CallbackQuery, state: FSMContext, db) -> None:
    tg_id = call.from_user.id
    data = await state.get_data()
    child = await q.get_child(db, data.get("child_id"), tg_id)
    if not child:
        await call.message.edit_text("Не нашёл ребёнка. Нажмите /start.")
        await state.clear()
        return

    hobby   = data.get("regen_hobby_text")
    comment = data.get("regen_comment")
    topic   = data.get("topic")
    anxiety = data.get("anxiety")

    text = (
        f"👦 <b>{child['name']}, {child['age']} лет</b>\n"
        f"🎯 Увлечение: <b>{hobby}</b>\n"
        f"📚 Тема: <b>{topic}</b>\n"
        f"😟 Тревожность: <b>{anxiety} из 10</b>"
    )
    if comment:
        text += f"\n💬 Комментарий: <b>«{comment}»</b>"

    await call.message.edit_text(text, reply_markup=regen_summary_kb())
    await state.set_state(Dialog.regen_summary)


@router.callback_query(Dialog.regen_comment, NavCb.filter(F.to == "regen_back"))
async def regen_back_to_answer(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    last = data.get("last_ai_text")
    if last:
        await call.message.edit_text(last, reply_markup=after_answer_kb())
        await state.set_state(Dialog.summary)
        return
    await call.answer()


@router.callback_query(Dialog.regen_summary, NavCb.filter(F.to == "regen_comment_back"))
async def regen_back_to_comment(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "Хотите добавить комментарий?\n"
        "Например: \"другой пример\", \"объяснить проще\", \"через голы и статистику\"",
        reply_markup=regen_comment_kb(),
    )
    await state.set_state(Dialog.regen_comment)


@router.callback_query(Dialog.regen_summary, SimpleCb.filter(F.action == "regen_generate"))
async def regen_generate(call: CallbackQuery, state: FSMContext, db, ai_client, admin_tg_id: int):
    data = await state.get_data()
    await _do_generate(
        call=call,
        state=state,
        db=db,
        ai_client=ai_client,
        admin_tg_id=admin_tg_id,
        comment=data.get("regen_comment"),
        override_hobby=data.get("regen_hobby_text"),
    )
