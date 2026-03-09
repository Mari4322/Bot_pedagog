from __future__ import annotations

import logging
import sys
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from openai import APIStatusError, RateLimitError

from database import queries as q

# Логгер: пишет в консоль И в файл bot_errors.log (рядом с bot.py)
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
from keyboards.callbacks import HobbyCb, NavCb, SimpleCb
from keyboards.user_kb import after_answer_kb, regen_comment_kb, regen_pick_hobby_kb, regen_summary_kb
from services.ai_service import AIResult, generate_response
from states import Dialog


router = Router()


async def _send_limit_message(call: CallbackQuery):
    await call.message.edit_text(
        "Вы исчерпали лимит запросов на сегодня. Возвращайтесь завтра или обновите тариф — /pay"
    )


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
    access = await q.get_access_state(db, tg_id)
    if not access.can_generate:
        await _send_limit_message(call)
        return

    data = await state.get_data()
    child = await q.get_child(db, data.get("child_id"), tg_id)
    if not child or child.get("age") is None:
        await call.message.edit_text("Не нашёл данные ребёнка. Нажмите /start.")
        await state.clear()
        return

    hobby = override_hobby or data.get("hobby_text")
    topic = data.get("topic")
    anxiety = data.get("anxiety")
    if not (hobby and topic and anxiety):
        await call.message.edit_text("Не хватает данных для генерации. Нажмите /start.")
        await state.clear()
        return

    model = await q.get_setting(db, "current_model") or "openai/gpt-4o"
    FALLBACK_MODEL = "openai/gpt-4o"  # модель, которая есть в polza.ai, если выбранная недоступна

    await call.message.edit_text("Готовлю объяснение, подождите... ⏳")

    try:
        result: AIResult = await generate_response(
            client=ai_client,
            model=model,
            child_name=child["name"],
            child_age=int(child["age"]),
            hobby=hobby,
            topic=topic,
            anxiety_level=int(anxiety),
            comment=comment,
        )
    except APIStatusError as e:
        _log.error("APIStatusError status=%s message=%s", e.status_code, e.message, exc_info=True)
        # Если модель не найдена (400) — переключаем на fallback и пробуем один раз
        if e.status_code == 400 and ("не найдена" in (e.message or "") or "not found" in (e.message or "").lower()):
            if model != FALLBACK_MODEL:
                await q.set_setting(db, "current_model", FALLBACK_MODEL)
                _log.info("Переключили current_model с %s на %s", model, FALLBACK_MODEL)
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
                    # Успех после смены модели — считаем и показываем ответ (код ниже в try не выполнится, поэтому делаем здесь)
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
                    return
                except Exception as retry_e:
                    _log.exception("Повторный запрос после смены модели тоже упал: %s", retry_e)
                    await call.message.edit_text(
                        "Выбранная модель недоступна в сервисе. Админ: смените модель через /change_model."
                    )
                    return
            else:
                await call.message.edit_text(
                    "Модель недоступна в сервисе. Админ: смените модель через /change_model."
                )
                return
        else:
            if e.status_code in (401, 402):
                await call.bot.send_message(admin_tg_id, f"polza.ai ошибка {e.status_code}: {e.message}")
            await call.message.edit_text("Ошибка при обращении к ИИ. Попробуйте позже.")
        return
    except RateLimitError as e:
        _log.error("RateLimitError: %s", e, exc_info=True)
        await call.message.edit_text("Слишком много запросов. Попробуйте ещё раз через минуту.")
        return
    except Exception as e:
        _log.exception("Ошибка генерации: %s: %s", type(e).__name__, e)
        try:
            await call.bot.send_message(admin_tg_id, f"Ошибка генерации: {type(e).__name__}: {e}")
        except Exception:
            pass
        await call.message.edit_text("Ошибка при обращении к ИИ. Попробуйте позже.")
        return

    # Успех: счётчик + лог
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


@router.callback_query(SimpleCb.filter(F.action == "generate"))
async def generate_from_summary(call: CallbackQuery, state: FSMContext, db, ai_client, admin_tg_id: int):
    await _do_generate(call=call, state=state, db=db, ai_client=ai_client, admin_tg_id=admin_tg_id)


@router.callback_query(SimpleCb.filter(F.action == "new"))
async def new_request(call: CallbackQuery, state: FSMContext, db):
    from handlers.dialog import show_step1

    await state.clear()
    await show_step1(call=call, state=state, db=db)


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
    await call.message.edit_text("Выберите увлечение для нового объяснения:", reply_markup=regen_pick_hobby_kb(hobbies))
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
        "Хотите добавить комментарий?\nНапример: \"другой пример\", \"объяснить проще\", \"через голы и статистику\"",
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
        await message.answer("Слишком длинно. Введите короче или нажмите «Пропустить».", reply_markup=regen_comment_kb())
        return
    await state.update_data(regen_comment=comment if comment else None)
    tg_id = message.from_user.id
    data = await state.get_data()
    child = await q.get_child(db, data.get("child_id"), tg_id)
    if not child:
        await message.answer("Не нашёл ребёнка. Нажмите /start.")
        await state.clear()
        return

    hobby = data.get("regen_hobby_text")
    topic = data.get("topic")
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


async def _show_regen_summary(*, call: CallbackQuery, state: FSMContext, db):
    tg_id = call.from_user.id
    data = await state.get_data()
    child = await q.get_child(db, data.get("child_id"), tg_id)
    if not child:
        await call.message.edit_text("Не нашёл ребёнка. Нажмите /start.")
        await state.clear()
        return

    hobby = data.get("regen_hobby_text")
    comment = data.get("regen_comment")
    topic = data.get("topic")
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
    # просто возвращаемся к последнему ответу, если он есть
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
        "Хотите добавить комментарий?\nНапример: \"другой пример\", \"объяснить проще\", \"через голы и статистику\"",
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

