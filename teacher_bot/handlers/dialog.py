from __future__ import annotations

"""
Диалог Шаги 1–6 (сбор данных) по ТЗ.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.filters.state import StateFilter
from aiogram.types import CallbackQuery, Message

from database import queries as q
from keyboards.callbacks import AnxietyCb, ChildCb, HobbyCb, NavCb, SimpleCb
from keyboards.user_kb import (
    anxiety_kb,
    back_kb,
    step1_children_kb,
    step2_age_kb,
    step3_hobbies_kb,
    summary_kb,
)
from states import Dialog


router = Router()


async def show_step1(*, message: Message | None = None, call: CallbackQuery | None = None, state: FSMContext, db):
    tg_id = (message.from_user.id if message else call.from_user.id)
    children = await q.list_children(db, tg_id)

    await state.clear()
    await state.update_data(child_id=None)

    if not children:
        text = "Давайте добавим ребёнка. Введите имя:"
        if message:
            await message.answer(text)
        else:
            await call.message.edit_text(text)
        await state.set_state(Dialog.child_name_input)
        await state.update_data(child_action="add")
        return

    text = "Выберите ребёнка или добавьте нового:"
    kb = step1_children_kb(children)
    if message:
        await message.answer(text, reply_markup=kb)
    else:
        await call.message.edit_text(text, reply_markup=kb)


async def show_step2(*, call: CallbackQuery, state: FSMContext, db):
    data = await state.get_data()
    child_id = data.get("child_id")
    tg_id = call.from_user.id
    child = await q.get_child(db, child_id, tg_id)
    if not child:
        await show_step1(call=call, state=state, db=db)
        return

    name = child["name"]
    age = child["age"]
    text = f"Ребёнок: <b>{name}</b>\nВозраст: <b>{age if age is not None else '—'}</b>"

    if age is None:
        await call.message.edit_text(f"Ребёнок: <b>{name}</b>\nВведите возраст (числом):", reply_markup=back_kb("step1"))
        await state.set_state(Dialog.child_age_input)
        return

    await call.message.edit_text(text, reply_markup=step2_age_kb(age))


async def show_step3(*, call: CallbackQuery, state: FSMContext, db):
    tg_id = call.from_user.id
    data = await state.get_data()
    child_id = data.get("child_id")
    child = await q.get_child(db, child_id, tg_id)
    if not child:
        await show_step1(call=call, state=state, db=db)
        return

    hobbies = await q.list_hobbies(db, child_id, tg_id)
    if not hobbies:
        await call.message.edit_text(f"Увлечения <b>{child['name']}</b>. Введите первое увлечение текстом:", reply_markup=back_kb("step2"))
        await state.set_state(Dialog.hobby_input)
        return

    await call.message.edit_text(
        f"Увлечения <b>{child['name']}</b>. Выберите одно для объяснения:",
        reply_markup=step3_hobbies_kb(hobbies),
    )
    await state.set_state(Dialog.hobby_pick)


async def show_step4(*, call: CallbackQuery, state: FSMContext, db):
    await call.message.edit_text(
        "Какую тему нужно объяснить?\nНапример: дроби, Вторая мировая война, фотосинтез",
        reply_markup=back_kb("step3"),
    )
    await state.set_state(Dialog.topic_input)


async def show_step5(*, call: CallbackQuery, state: FSMContext, db):
    await call.message.edit_text(
        "Насколько ребёнок тревожится по поводу этой темы?\n"
        "Выберите по шкале от 1 до 10, где <b>10 — очень тревожно</b>:",
        reply_markup=anxiety_kb(),
    )
    await state.set_state(Dialog.anxiety_pick)


async def show_summary(*, call: CallbackQuery, state: FSMContext, db):
    tg_id = call.from_user.id
    data = await state.get_data()
    child = await q.get_child(db, data["child_id"], tg_id)
    if not child:
        await show_step1(call=call, state=state, db=db)
        return

    hobby_text = data.get("hobby_text")
    topic = data.get("topic")
    anxiety = data.get("anxiety")

    text = (
        "Всё готово! Проверьте данные:\n\n"
        f"👦 <b>{child['name']}, {child['age']} лет</b>\n"
        f"🎯 Увлечение: <b>{hobby_text}</b>\n"
        f"📚 Тема: <b>{topic}</b>\n"
        f"😟 Тревожность: <b>{anxiety} из 10</b>"
    )
    await call.message.edit_text(text, reply_markup=summary_kb())
    await state.set_state(Dialog.summary)


@router.callback_query(NavCb.filter())
async def on_nav(call: CallbackQuery, callback_data: NavCb, state: FSMContext, db):
    to = callback_data.to
    if to == "step1":
        await show_step1(call=call, state=state, db=db)
    elif to == "step2":
        await show_step2(call=call, state=state, db=db)
    elif to == "step3":
        await show_step3(call=call, state=state, db=db)
    elif to == "step4":
        await show_step4(call=call, state=state, db=db)
    elif to == "step5":
        await show_step5(call=call, state=state, db=db)
    else:
        await call.answer()


@router.callback_query(ChildCb.filter(F.action == "select"))
async def child_select(call: CallbackQuery, callback_data: ChildCb, state: FSMContext, db):
    await state.update_data(child_id=callback_data.child_id)
    await show_step2(call=call, state=state, db=db)


@router.callback_query(ChildCb.filter(F.action == "edit"))
async def child_edit(call: CallbackQuery, callback_data: ChildCb, state: FSMContext, db):
    await state.update_data(child_id=callback_data.child_id, child_action="rename")
    await call.message.edit_text("Введите новое имя ребёнка:", reply_markup=back_kb("step1"))
    await state.set_state(Dialog.child_rename_input)


@router.callback_query(SimpleCb.filter(F.action == "add_child"))
async def child_add(call: CallbackQuery, state: FSMContext):
    await state.update_data(child_action="add")
    await call.message.edit_text("Введите имя ребёнка:", reply_markup=back_kb("step1"))
    await state.set_state(Dialog.child_name_input)


@router.message(Dialog.child_name_input)
async def child_name_input(message: Message, state: FSMContext, db):
    name = (message.text or "").strip()
    if len(name) < 1:
        await message.answer("Введите имя текстом.")
        return
    if len(name) > 64:
        await message.answer("Слишком длинное имя. Введите короче.")
        return

    action = (await state.get_data()).get("child_action")
    tg_id = message.from_user.id

    if action == "add":
        child_id = await q.add_child(db, tg_id, name)
        await state.update_data(child_id=child_id)
        await message.answer(f"Ребёнок: <b>{name}</b>\nВведите возраст (числом):", reply_markup=back_kb("step1"))
        await state.set_state(Dialog.child_age_input)
        return

    await message.answer("Не понял действие. Нажмите /start.")


@router.message(Dialog.child_rename_input)
async def child_rename_input(message: Message, state: FSMContext, db):
    name = (message.text or "").strip()
    if len(name) < 1:
        await message.answer("Введите имя текстом.")
        return
    if len(name) > 64:
        await message.answer("Слишком длинное имя. Введите короче.")
        return

    tg_id = message.from_user.id
    child_id = (await state.get_data()).get("child_id")
    await q.rename_child(db, child_id, tg_id, name)
    children = await q.list_children(db, tg_id)
    await message.answer("Готово. Выберите ребёнка:", reply_markup=step1_children_kb(children))
    await state.clear()


@router.callback_query(SimpleCb.filter(F.action.in_(["confirm_age", "change_age"])))
async def age_actions(call: CallbackQuery, callback_data: SimpleCb, state: FSMContext, db):
    if callback_data.action == "confirm_age":
        await show_step3(call=call, state=state, db=db)
        return
    await call.message.edit_text("Введите новый возраст (числом):", reply_markup=back_kb("step2"))
    await state.set_state(Dialog.child_age_input)


@router.message(Dialog.child_age_input)
async def child_age_input(message: Message, state: FSMContext, db):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Возраст должен быть числом. Например: 10")
        return
    age = int(raw)
    if not (1 <= age <= 25):
        await message.answer("Введите возраст от 1 до 25.")
        return

    tg_id = message.from_user.id
    child_id = (await state.get_data()).get("child_id")
    await q.set_child_age(db, child_id, tg_id, age)

    child = await q.get_child(db, child_id, tg_id)
    if not child:
        await message.answer("Не нашёл ребёнка. Нажмите /start.")
        return

    hobbies = await q.list_hobbies(db, child_id, tg_id)
    if not hobbies:
        await message.answer(
            f"Увлечения <b>{child['name']}</b>. Введите первое увлечение текстом:",
            reply_markup=back_kb("step2"),
        )
        await state.set_state(Dialog.hobby_input)
        return

    await message.answer(
        f"Увлечения <b>{child['name']}</b>. Выберите одно для объяснения:",
        reply_markup=step3_hobbies_kb(hobbies),
    )
    await state.set_state(Dialog.hobby_pick)


@router.callback_query(SimpleCb.filter(F.action == "add_hobby"))
async def hobby_add(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите увлечение текстом:", reply_markup=back_kb("step3"))
    await state.set_state(Dialog.hobby_input)


@router.message(Dialog.hobby_pick)
async def hobby_pick_text(message: Message, state: FSMContext, db):
    tg_id = message.from_user.id
    data = await state.get_data()
    child_id = data.get("child_id")
    hobbies = await q.list_hobbies(db, child_id, tg_id)
    await message.answer(
        "Выберите увлечение из списка или нажмите <b>«+ Добавить увлечение»</b>:",
        reply_markup=step3_hobbies_kb(hobbies),
    )


@router.message(Dialog.hobby_input)
async def hobby_input(message: Message, state: FSMContext, db):
    hobby = (message.text or "").strip()
    if len(hobby) < 1:
        await message.answer("Введите увлечение текстом.")
        return
    if len(hobby) > 64:
        await message.answer("Слишком длинно. Введите короче.")
        return

    tg_id = message.from_user.id
    child_id = (await state.get_data()).get("child_id")
    res = await q.add_hobby(db, child_id, tg_id, hobby)
    if res is None:
        await message.answer("Не нашёл ребёнка. Нажмите /start.")
        return

    hobbies = await q.list_hobbies(db, child_id, tg_id)
    await message.answer("Добавлено. Выберите увлечение:", reply_markup=step3_hobbies_kb(hobbies))
    await state.set_state(Dialog.hobby_pick)


@router.callback_query(HobbyCb.filter(F.action == "del"))
async def hobby_delete(call: CallbackQuery, callback_data: HobbyCb, state: FSMContext, db):
    tg_id = call.from_user.id
    await q.delete_hobby(db, callback_data.hobby_id, tg_id)

    data = await state.get_data()
    child_id = data.get("child_id")
    hobbies = await q.list_hobbies(db, child_id, tg_id)
    child = await q.get_child(db, child_id, tg_id)
    if not child:
        await show_step1(call=call, state=state, db=db)
        return

    if not hobbies:
        await call.message.edit_text(f"Увлечения <b>{child['name']}</b>. Введите первое увлечение текстом:", reply_markup=back_kb("step2"))
        await state.set_state(Dialog.hobby_input)
        return

    await call.message.edit_text(
        f"Увлечения <b>{child['name']}</b>. Выберите одно для объяснения:",
        reply_markup=step3_hobbies_kb(hobbies),
    )
    await state.set_state(Dialog.hobby_pick)
    await call.answer("Удалено")


@router.callback_query(
    HobbyCb.filter(F.action == "select"),
    StateFilter(
        None,
        Dialog.child_name_input, Dialog.child_rename_input, Dialog.child_age_input,
        Dialog.hobby_pick, Dialog.hobby_input, Dialog.topic_input, Dialog.anxiety_pick, Dialog.summary,
    ),
)
async def hobby_select(call: CallbackQuery, callback_data: HobbyCb, state: FSMContext, db):
    tg_id = call.from_user.id
    data = await state.get_data()
    child_id = data.get("child_id")
    hobbies = await q.list_hobbies(db, child_id, tg_id)
    chosen = next((h for h in hobbies if h["id"] == callback_data.hobby_id), None)
    if not chosen:
        await call.answer()
        return

    await state.update_data(hobby_id=callback_data.hobby_id, hobby_text=chosen["hobby"])
    await show_step4(call=call, state=state, db=db)


@router.message(Dialog.topic_input)
async def topic_input(message: Message, state: FSMContext):
    topic = (message.text or "").strip()
    if len(topic) < 2:
        await message.answer("Введите тему текстом. Например: дроби")
        return
    if len(topic) > 200:
        await message.answer("Слишком длинная тема. Введите короче.")
        return
    await state.update_data(topic=topic)
    await message.answer(
        "Насколько ребёнок тревожится по поводу этой темы?\n"
        "Выберите по шкале от 1 до 10, где <b>10 — очень тревожно</b>:",
        reply_markup=anxiety_kb(),
    )
    await state.set_state(Dialog.anxiety_pick)


@router.callback_query(AnxietyCb.filter())
async def anxiety_pick(call: CallbackQuery, callback_data: AnxietyCb, state: FSMContext, db):
    await state.update_data(anxiety=callback_data.value)
    await show_summary(call=call, state=state, db=db)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db):
    await state.clear()
    await message.answer("Ок, начнём сначала.")
    await show_step1(message=message, state=state, db=db)
