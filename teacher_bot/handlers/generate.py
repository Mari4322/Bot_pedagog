from __future__ import annotations

"""
Хендлеры генерации и перегенерации (Шаги 7–8 по ТЗ).

Ключевые правила:
- Счётчик daily_count увеличивается ТОЛЬКО при успешном ответе ИИ.
- При ЛЮБОЙ ошибке API счётчик НЕ увеличивается.
- Пользователь НИКОГДА не видит технических деталей (коды ошибок, названия моделей и т.д.)
  — только вежливое сообщение с просьбой попробовать ещё раз.
- Все технические детали идут в лог-файл и/или личное сообщение администратору.
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

# Единственное сообщение об ошибке, которое видит пользователь при любой проблеме с ИИ
_USER_ERROR_MSG = "Извините, что-то пошло не так. Попробуйте ещё раз 🙏"


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
        _log.warning("408 Timeout tg_id=%d model=%s", tg_id, model)
        await call.message.edit_text(_USER_ERROR_MSG)
        return

    # ── 500 — ошибка сервера ──────────────────────────────────────────────
    except ServerAPIError as e:
        _log.error("500 Server error tg_id=%d model=%s: %s", tg_id, model, e.message)
        await _notify_admin(call, admin_tg_id,
                            f"⚠️ polza.ai 500 | tg_id={tg_id} | model={model}\n{e.message}")
        await call.message.edit_text(_USER_ERROR_MSG)
        return

    # ── APIStatusError ─────────────────────────────────────────────────────
    except APIStatusError as e:
        code = e.status_code
        _log.error("APIStatusError %d tg_id=%d model=%s: %s", code, tg_id, model, e.message)

        # 400 — модель не найдена → тихий fallback, пользователь не замечает
        if code == 400 and (
            "не найдена" in (e.message or "")
            or "not found" in (e.message or "").lower()
        ):
            if model != FALLBACK_MODEL:
                await q.set_setting(db, "current_model", FALLBACK_MODEL)
                _log.info("Автосмена модели %s → %s", model, FALLBACK_MODEL)
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
                    await _save_and_show(
                        call=call, state=state, db=db,
                        tg_id=tg_id, child=child,
                        hobby=hobby, comment=comment,
                        topic=topic, anxiety=anxiety,
                        result=result,
                    )
                    return
                except Exception as retry_e:
                    _log.exception("Fallback тоже упал tg_id=%d: %s", tg_id, retry_e)
                    await _notify_admin(call, admin_tg_id,
                                        f"⚠️ Fallback model тоже упал | tg_id={tg_id}\n{type(retry_e).__name__}: {retry_e}")
                    await call.message.edit_text(_USER_ERROR_MSG)
                    return
            # fallback уже использован — просто показываем извинение
            await call.message.edit_text(_USER_ERROR_MSG)
            return

        # 401 — неверный API-ключ → только админу
        if code == 401:
            await _notify_admin(call, admin_tg_id,
                                f"🔑 polza.ai 401 (неверный API-ключ) | tg_id={tg_id}")
            await call.message.edit_text(_USER_ERROR_MSG)
            return

        # 402 — нет средств → только админу
        if code == 402:
            await _notify_admin(call, admin_tg_id,
                                f"💳 polza.ai 402 (недостаточно средств) | tg_id={tg_id}")
            await call.message.edit_text(_USER_ERROR_MSG)
            return

        # 403 / 429 / 502 / 503 и прочие — лог уже есть, пользователю только извинение
        await _notify_admin(call, admin_tg_id,
                            f"polza.ai {code} | tg_id={tg_id} | model={model}\n{e.message}")
        await call.message.edit_text(_USER_ERROR_MSG)
        return

    # ── 429 RateLimitError — все retry исчерпаны ─────────────────────────
    except RateLimitError as e:
        _log.error("429 RateLimit exhausted tg_id=%d: %s", tg_id, e)
        await call.message.edit_text(_USER_ERROR_MSG)
        return

    # ── Нет соединения ───────────────────────────────────────────────────
    except APIConnectionError as e:
        _log.error("APIConnectionError exhausted tg_id=%d: %s", tg_id, e)
        await call.message.edit_text(_USER_ERROR_MSG)
        return

    # ── Любая неожиданная ошибка ─────────────────────────────────────────
    except Exception as e:
        _log.exception("Unexpected error tg_id=%d: %s: %s", tg_id, type(e).__name__, e)
        await _notify_admin(call, admin_tg_id,
                            f"❗ Неожиданная ошибка | tg_id={tg_id}\n{type(e).__name__}: {e}")
        await call.message.edit_text(_USER_ERROR_MSG)
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
