"""FSM states for the upload flow (aiogram 3)."""
from aiogram.fsm.state import State, StatesGroup


class Upload(StatesGroup):
    department = State()   # waiting for a department button
    year = State()         # waiting for a year button
    semester = State()     # waiting for a semester button
    type = State()         # waiting for a resource type button
    course_name = State()  # waiting for the typed course name
    confirm = State()      # summary shown, waiting for Confirm / Edit / Cancel
    uploading = State()    # collecting files until Done
