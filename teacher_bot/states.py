from aiogram.fsm.state import State, StatesGroup


class Dialog(StatesGroup):
    child_name_input = State()
    child_rename_input = State()
    child_age_input = State()
    hobby_input = State()
    topic_input = State()
    anxiety_pick = State()
    summary = State()

    regen_pick_hobby = State()
    regen_comment = State()
    regen_summary = State()

