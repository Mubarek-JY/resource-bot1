"""Handlers for the resource-collection flow.

Spec for every handler is in README.md section 7 and 9. IMPORTANT: aiogram
tries handlers in registration order within a router, so keep this order:
commands first, then the cancel button, then state-specific handlers, then the
fallbacks at the bottom.
"""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

import keyboards
from config import (
    ADMIN_ID,
    CHANNEL_ID,
    INCLUDE_UPLOADER,
    MAX_COURSE_NAME_LENGTH,
    MAX_FILES_PER_SESSION,
    SEND_DELAY_SECONDS,
)
from data import (
    DEPARTMENTS_BY_TAG,
    FRESHMAN_TAG,
    NON_FRESHMAN_YEARS,
    SEMESTERS,
    TYPES_BY_CODE,
    years_for_department,
)
from states import Upload

log = logging.getLogger(__name__)

router = Router()
# Private chats only: ignore the bot being added to groups.
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

# FSM data keys (state.update_data / state.get_data):
#   dept_tag, year, semester, type_code, course, prompt_msg_id,
#   file_msg_ids (list[int]), sending (bool)

# ------------------------------------------------------------------ texts

WELCOME_TEXT = "Welcome! This bot collects university resources.\n\nChoose the department:"
CANCELLED_TEXT = "Cancelled. Send /start to begin again."
CHOOSE_YEAR = "Choose the year:"
CHOOSE_SEMESTER = "Choose the semester:"
CHOOSE_TYPE = "Choose the resource type:"
TYPE_COURSE = "Type the course name (for example: Data Structures):"
UPLOAD_PROMPT = (
    "Send your file(s). Please send them as File (not compressed photos) "
    "to keep the quality.\nTap Done when finished."
)
COURSE_HINT = f"Please type a course name between 2 and {MAX_COURSE_NAME_LENGTH} characters."
COURSE_NOT_TEXT = "Please type the course name as text."
USE_BUTTONS = "Please use the buttons above."
NO_SESSION = "Send /start to add a resource."
SEND_FILE_OR_DONE = "Please send a file, or tap Done above."
EXPIRED = "This menu has expired. Send /start to begin again."
NO_FILES = "No files yet. Send at least one file."
ALREADY_SENDING = "Already sending..."
TOO_MANY_FILES = f"Limit reached: at most {MAX_FILES_PER_SESSION} files per upload. Tap Done."
SEND_ERROR = "Something went wrong while sending. Send /start to try again."

BUTTON_STEP_STATES = {
    Upload.department.state,
    Upload.year.state,
    Upload.semester.state,
    Upload.type.state,
    Upload.confirm.state,
}

# Keep references to fire-and-forget tasks so they are not garbage collected.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------- helpers

def progress_text(data: dict, upto: str) -> str:
    """Lines of the choices made so far, up to and including `upto`
    (one of dept, year, sem, type)."""
    order = ["dept", "year", "sem", "type"]
    lines = []
    if "dept_tag" in data and order.index(upto) >= 0:
        lines.append(f"Department: {DEPARTMENTS_BY_TAG[data['dept_tag']]}")
    if "year" in data and order.index(upto) >= 1:
        lines.append(f"Year: {data['year']}")
    if "semester" in data and order.index(upto) >= 2:
        lines.append(f"Semester: {data['semester']}")
    if "type_code" in data and order.index(upto) >= 3:
        lines.append(f"Type: {TYPES_BY_CODE[data['type_code']][0]}")
    return "\n".join(lines)


def summary_text(data: dict) -> str:
    """Multi-line confirm summary. README section 7, step 6."""
    return (
        "Please confirm:\n"
        f"{progress_text(data, 'type')}\n"
        f"Course: {data['course']}"
    )


def build_caption(data: dict, user: User) -> str:
    """Channel caption. README section 8."""
    tag = data["dept_tag"]
    type_tag = TYPES_BY_CODE[data["type_code"]][1]
    lines = [
        f"#{tag} #Y{data['year']} #S{data['semester']} #{type_tag}",
        f"Course: {data['course']}",
    ]
    if INCLUDE_UPLOADER:
        who = f"@{user.username}" if user.username else str(user.id)
        lines.append(f"From: {who}")
    caption = "\n".join(lines)
    assert len(caption) <= 1024, "caption too long"
    return caption


async def copy_files_to_channel(
    bot: Bot, from_chat_id: int, message_ids: list[int], caption: str
) -> tuple[int, int]:
    """Copy each message into the channel one at a time. Returns (sent, failed)."""
    sent = failed = 0
    for index, mid in enumerate(message_ids):
        for _attempt in range(5):
            try:
                await bot.copy_message(
                    chat_id=CHANNEL_ID,
                    from_chat_id=from_chat_id,
                    message_id=mid,
                    caption=caption,
                )
                sent += 1
                break
            except TelegramRetryAfter as e:
                log.warning("Rate limited, sleeping %s s", e.retry_after)
                await asyncio.sleep(e.retry_after)
            except TelegramAPIError as e:
                log.warning("Could not copy message %s: %s", mid, e)
                failed += 1
                break
        else:
            failed += 1  # gave up after repeated rate limiting
        if index < len(message_ids) - 1:
            await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent, failed


async def edit_prompt(bot: Bot, chat_id: int, message_id: int, text: str, reply_markup=None) -> None:
    """Edit the single prompt message in place; never raises on Telegram errors."""
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            log.warning("edit_prompt failed: %s", e)


async def _edit_from_callback(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    msg = callback.message
    await edit_prompt(callback.bot, msg.chat.id, msg.message_id, text, reply_markup)


async def _delete_quietly(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError:
        pass


async def _delete_later(bot: Bot, chat_id: int, message_ids: list[int], delay: float = 5) -> None:
    await asyncio.sleep(delay)
    for mid in message_ids:
        await _delete_quietly(bot, chat_id, mid)


async def _cancel_session(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit_from_callback(callback, CANCELLED_TEXT)
    await callback.answer()


async def notify_admin(bot: Bot, text: str) -> None:
    """Send an operational alert without letting alert delivery break the bot."""
    if ADMIN_ID is None:
        return
    try:
        await bot.send_message(ADMIN_ID, text[:4000])
    except Exception:
        log.exception("Could not notify admin")


# --------------------------------------------------------------- commands

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    sent = await message.answer(WELCOME_TEXT, reply_markup=keyboards.department_kb())
    await state.update_data(prompt_msg_id=sent.message_id)
    await state.set_state(Upload.department)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(CANCELLED_TEXT)


# ---------------------------------------------------------- cancel button

@router.callback_query(F.data == "cancel")
async def on_cancel_button(callback: CallbackQuery, state: FSMContext) -> None:
    await _cancel_session(callback, state)


@router.callback_query(F.data == "back")
async def on_back_button(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    data = await state.get_data()
    if current == Upload.semester.state and data.get("dept_tag") == FRESHMAN_TAG:
        for key in ("year", "semester", "type_code", "course"):
            data.pop(key, None)
        await state.set_data(data)
        await state.set_state(Upload.department)
        await _edit_from_callback(callback, "Choose the department:", keyboards.department_kb())
        await callback.answer()
        return
    steps = {
        Upload.year.state: (Upload.department, keyboards.department_kb, "Choose the department:",
                            ("dept_tag", "year", "semester", "type_code", "course")),
        Upload.semester.state: (Upload.year,
                                lambda: keyboards.year_kb(
                                    years=years_for_department(data.get("dept_tag", "")), back=True
                                ),
                                CHOOSE_YEAR,
                                ("year", "semester", "type_code", "course")),
        Upload.type.state: (Upload.semester, lambda: keyboards.semester_kb(back=True), CHOOSE_SEMESTER,
                            ("semester", "type_code", "course")),
        Upload.course_name.state: (Upload.type, lambda: keyboards.type_kb(back=True), CHOOSE_TYPE,
                                   ("type_code", "course")),
    }
    step = steps.get(current)
    if step is None:
        await callback.answer(EXPIRED, show_alert=True)
        return
    target, keyboard, prompt, keys_to_clear = step
    for key in keys_to_clear:
        data.pop(key, None)
    await state.set_data(data)
    await state.set_state(target)
    upto_by_state = {
        Upload.year.state: "dept",
        Upload.semester.state: "year",
        Upload.type.state: "sem",
    }
    upto = upto_by_state.get(target.state)
    if upto:
        prompt = f"{progress_text(data, upto)}\n\n{prompt}"
    await _edit_from_callback(callback, prompt, keyboard())
    await callback.answer()


# ------------------------------------------------------ button-step flow

@router.callback_query(Upload.department, F.data.startswith("dept:"))
async def on_department(callback: CallbackQuery, state: FSMContext) -> None:
    tag = callback.data.split(":", 1)[1]
    if tag not in DEPARTMENTS_BY_TAG:
        await callback.answer("Unknown department.", show_alert=True)
        return
    await state.update_data(dept_tag=tag)
    data = await state.get_data()
    if tag == FRESHMAN_TAG:
        await state.update_data(year=1)
        await state.set_state(Upload.semester)
        data = await state.get_data()
        await _edit_from_callback(
            callback,
            f"{progress_text(data, 'year')}\n\n{CHOOSE_SEMESTER}",
            keyboards.semester_kb(back=True),
        )
        await callback.answer()
        return
    await state.set_state(Upload.year)
    await _edit_from_callback(
        callback,
        f"{progress_text(data, 'dept')}\n\n{CHOOSE_YEAR}",
        keyboards.year_kb(years=years_for_department(tag), back=True),
    )
    await callback.answer()


@router.callback_query(Upload.year, F.data.startswith("year:"))
async def on_year(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    data = await state.get_data()
    dept_tag = data.get("dept_tag")
    valid_years = years_for_department(dept_tag) if dept_tag else NON_FRESHMAN_YEARS
    if not raw.isdigit() or int(raw) not in valid_years:
        await callback.answer("Invalid year.", show_alert=True)
        return
    await state.update_data(year=int(raw))
    data = await state.get_data()
    await state.set_state(Upload.semester)
    await _edit_from_callback(
        callback, f"{progress_text(data, 'year')}\n\n{CHOOSE_SEMESTER}", keyboards.semester_kb(back=True)
    )
    await callback.answer()


@router.callback_query(Upload.semester, F.data.startswith("sem:"))
async def on_semester(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    if not raw.isdigit() or int(raw) not in SEMESTERS:
        await callback.answer("Invalid semester.", show_alert=True)
        return
    await state.update_data(semester=int(raw))
    data = await state.get_data()
    await state.set_state(Upload.type)
    await _edit_from_callback(
        callback, f"{progress_text(data, 'sem')}\n\n{CHOOSE_TYPE}", keyboards.type_kb(back=True)
    )
    await callback.answer()


@router.callback_query(Upload.type, F.data.startswith("type:"))
async def on_type(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":", 1)[1]
    if code not in TYPES_BY_CODE:
        await callback.answer("Unknown type.", show_alert=True)
        return
    await state.update_data(type_code=code)
    data = await state.get_data()
    await state.set_state(Upload.course_name)
    await _edit_from_callback(
        callback, f"{progress_text(data, 'type')}\n\n{TYPE_COURSE}", keyboards.cancel_only_kb(back=True)
    )
    await callback.answer()


# ----------------------------------------------------------- course name

@router.message(Upload.course_name, F.text)
async def on_course_name(message: Message, state: FSMContext, bot: Bot) -> None:
    course = " ".join(message.text.split())
    if not 2 <= len(course) <= MAX_COURSE_NAME_LENGTH:
        hint = await message.answer(COURSE_HINT)
        _spawn(_delete_later(bot, message.chat.id, [message.message_id, hint.message_id]))
        return
    await state.update_data(course=course)
    data = await state.get_data()
    await _delete_quietly(bot, message.chat.id, message.message_id)
    await state.set_state(Upload.confirm)
    await edit_prompt(
        bot, message.chat.id, data["prompt_msg_id"], summary_text(data), keyboards.confirm_kb()
    )


@router.message(Upload.course_name)
async def on_course_name_not_text(message: Message) -> None:
    await message.answer(COURSE_NOT_TEXT)


# --------------------------------------------------------------- confirm

@router.callback_query(Upload.confirm, F.data.startswith("confirm:"))
async def on_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "yes":
        await state.update_data(file_msg_ids=[], sending=False)
        await state.set_state(Upload.uploading)
        await _edit_from_callback(
            callback, f"{UPLOAD_PROMPT}\n\nFiles received: 0", keyboards.upload_kb()
        )
        await callback.answer()
    elif action == "edit":
        data = await state.get_data()
        await state.set_state(Upload.course_name)
        await _edit_from_callback(
            callback, f"{progress_text(data, 'type')}\n\n{TYPE_COURSE}", keyboards.cancel_only_kb(back=True)
        )
        await callback.answer()
    elif action == "cancel":
        await _cancel_session(callback, state)
    else:
        await callback.answer("Unknown action.", show_alert=True)


# ------------------------------------------------------------- uploading

@router.message(Upload.uploading, F.document | F.photo | F.video | F.audio)
async def on_file(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    ids: list[int] = list(data.get("file_msg_ids", []))
    if len(ids) >= MAX_FILES_PER_SESSION:
        await message.reply(TOO_MANY_FILES)
        return
    ids.append(message.message_id)
    await state.update_data(file_msg_ids=ids)
    count = len(ids)

    # Debounce: albums arrive as many messages; only the last one edits the counter.
    await asyncio.sleep(0.8)
    latest = await state.get_data()
    if len(latest.get("file_msg_ids", [])) == count and latest.get("prompt_msg_id"):
        await edit_prompt(
            bot,
            message.chat.id,
            latest["prompt_msg_id"],
            f"{UPLOAD_PROMPT}\n\nFiles received: {count}",
            keyboards.upload_kb(),
        )


@router.message(Upload.uploading)
async def on_uploading_other(message: Message) -> None:
    await message.answer(SEND_FILE_OR_DONE)


@router.callback_query(Upload.uploading, F.data == "done")
async def on_done(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    file_ids: list[int] = data.get("file_msg_ids", [])
    if not file_ids:
        await callback.answer(NO_FILES, show_alert=True)
        return
    if data.get("sending"):
        await callback.answer(ALREADY_SENDING)
        return
    await state.update_data(sending=True)
    await callback.answer()
    chat_id = callback.message.chat.id
    await _edit_from_callback(callback, f"Sending {len(file_ids)} file(s)... please wait.")
    try:
        caption = build_caption(data, callback.from_user)
        sent, failed = await copy_files_to_channel(bot, chat_id, file_ids, caption)
    except Exception:
        log.exception("Upload failed for user %s", callback.from_user.id)
        await notify_admin(
            bot,
            f"Resource upload failed for user {callback.from_user.id} "
            f"(@{callback.from_user.username or 'no username'}). Check Render logs for details.",
        )
        await state.clear()
        await _edit_from_callback(callback, SEND_ERROR)
        return
    total = len(file_ids)
    text = f"Sent {sent} of {total} file(s). Thank you!\nSend /start to add another resource."
    if failed:
        text += f"\n{failed} file(s) could not be sent."
        await notify_admin(
            bot,
            f"Resource send failures: {failed}/{total} file(s) failed for user "
            f"{callback.from_user.id} (@{callback.from_user.username or 'no username'}).",
        )
    # Keep the upload prompt out of the conversation after completion. Send the
    # result as a fresh message once all channel copies have finished.
    await _delete_quietly(bot, chat_id, callback.message.message_id)
    await bot.send_message(chat_id, text)
    await state.clear()
    log.info(
        "Upload done: user=%s dept=%s year=%s sem=%s type=%s sent=%s failed=%s",
        callback.from_user.id,
        data.get("dept_tag"),
        data.get("year"),
        data.get("semester"),
        data.get("type_code"),
        sent,
        failed,
    )


# ------------------------------------------------------------- fallbacks
# Keep these LAST.

@router.callback_query()
async def on_stale_callback(callback: CallbackQuery) -> None:
    await callback.answer(EXPIRED, show_alert=True)


@router.message()
async def on_unexpected_message(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current in BUTTON_STEP_STATES:
        await message.answer(USE_BUTTONS)
    else:
        await message.answer(NO_SESSION)
