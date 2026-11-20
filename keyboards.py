"""Inline keyboard builders. See README.md section 7 for layouts and callback data.

Every keyboard except the confirm keyboard ends with a full-width Cancel button
(callback_data="cancel").
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import DEPARTMENTS, SEMESTERS, TYPES, YEARS


def _cancel_button(data: str = "cancel") -> InlineKeyboardButton:
    return InlineKeyboardButton(text="Cancel", callback_data=data)


def department_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for name, tag in DEPARTMENTS:
        b.button(text=name, callback_data=f"dept:{tag}")
    b.add(_cancel_button())
    rows = len(DEPARTMENTS)
    b.adjust(*([2] * (rows // 2)), *([1] if rows % 2 else []), 1)
    return b.as_markup()


def year_kb(*, years: list[int] = YEARS, back: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in years:
        b.button(text=str(n), callback_data=f"year:{n}")
    b.add(_cancel_button())
    if back:
        b.button(text="Back", callback_data="back")
    b.adjust(len(years), 1, *([1] if back else []))
    return b.as_markup()


def semester_kb(*, back: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in SEMESTERS:
        b.button(text=str(n), callback_data=f"sem:{n}")
    b.add(_cancel_button())
    if back:
        b.button(text="Back", callback_data="back")
    b.adjust(len(SEMESTERS), 1, *([1] if back else []))
    return b.as_markup()


def type_kb(*, back: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, label, _tag in TYPES:
        b.button(text=label, callback_data=f"type:{code}")
    b.add(_cancel_button())
    if back:
        b.button(text="Back", callback_data="back")
    n = len(TYPES)
    b.adjust(*([2] * (n // 2)), *([1] if n % 2 else []), 1, *([1] if back else []))
    return b.as_markup()


def cancel_only_kb(*, back: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(_cancel_button())
    if back:
        b.button(text="Back", callback_data="back")
        b.adjust(1, 1)
    return b.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Confirm", callback_data="confirm:yes")
    b.button(text="Edit course name", callback_data="confirm:edit")
    b.button(text="Cancel", callback_data="confirm:cancel")
    b.adjust(2, 1)
    return b.as_markup()


def upload_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Done", callback_data="done")
    b.button(text="Cancel", callback_data="cancel")
    b.adjust(2)
    return b.as_markup()
