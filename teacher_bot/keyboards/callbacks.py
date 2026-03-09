from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class ChildCb(CallbackData, prefix="child"):
    action: str  # select | edit
    child_id: int


class HobbyCb(CallbackData, prefix="hobby"):
    action: str  # select | del
    hobby_id: int


class NavCb(CallbackData, prefix="nav"):
    to: str  # step1 | step2 | step3 | step4 | step5 | summary | regen_back


class SimpleCb(CallbackData, prefix="s"):
    action: str  # add_child | add_hobby | confirm_age | change_age | generate | regen | new | skip_comment | regen_generate


class AnxietyCb(CallbackData, prefix="anx"):
    value: int


class ModelCb(CallbackData, prefix="model"):
    model_id: str

