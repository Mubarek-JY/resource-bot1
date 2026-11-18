# University Resource Collector Bot (Telegram)

A Telegram bot that collects university study resources (exams, slides, references, modules) from students and posts them, tagged, into a private Telegram channel. This README is the implementation spec: another developer or AI should be able to finish the project from it alone.

Status: complete. All modules implemented; runs as webhook on Render (when RENDER_EXTERNAL_URL is set) or long polling locally.

---

## 1. Goal

Students send files to the bot. For each upload batch the student chooses department, year, semester and resource type with buttons, and types the course name. The bot then copies the files into a private channel with a hashtag caption, so the files can be browsed and searched inside Telegram.

## 2. Non-goals (version 1)

- No database. The channel is the only storage; it will be reorganised later by hand or by another tool.
- No retrieval, search or download commands in the bot.
- No admin panel, moderation, duplicate detection or user accounts.
- No webhooks; long polling only.

## 3. Stack

- Python 3.11+
- aiogram 3.x (FSM with `MemoryStorage`)
- python-dotenv
- Long polling. In-progress sessions are lost when the bot restarts. That is acceptable.

## 4. Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in BOT_TOKEN and CHANNEL_ID
python bot.py
```

Prerequisites (already done by the project owner): a bot created in @BotFather, a private channel, the bot added to the channel as admin with the "Post messages" permission.

## 5. Configuration (`.env`)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `BOT_TOKEN` | yes | | Token from @BotFather |
| `CHANNEL_ID` | yes | | Destination channel id, with the `-100` prefix (looks like `-100xxxxxxxxxx`) |
| `ADMIN_ID` | no | | Telegram numeric user id for startup and send failure alerts |
| `INCLUDE_UPLOADER` | no | `true` | Add a `From:` line to the caption |
| `MAX_FILES_PER_SESSION` | no | `30` | Cap on files per upload session |
| `SEND_DELAY_SECONDS` | no | `3` | Pause between channel posts (rate limits) |

Never commit `.env`, never print the token in logs, never hardcode either value.

## 6. Project layout

```
bot.py            entry point (done)
config.py         env loading and constants (done)
data.py           departments, years, semesters, types (done)
states.py         FSM states (done)
keyboards.py      inline keyboards (TODO)
handlers.py       all handlers and helpers (TODO)
.env.example      template for .env (done)
requirements.txt  dependencies (done)
```

## 7. User flow (exact spec)

The bot works in private chats only. During the button steps it uses **one single message** and edits it in place at each step (`callback.message.edit_text`). Always call `callback.answer()` so the button spinner stops.

Each prompt repeats the choices made so far, so the student always sees context.

**Step 0: `/start`**
- Clears any previous session.
- Sends: `Welcome! This bot collects university resources.\n\nChoose the department:` with the department keyboard.
- Saves that message's id as `prompt_msg_id`. State: `Upload.department`.

**Step 1: department** (state `Upload.department`)
- Keyboard: 13 buttons from `data.DEPARTMENTS`, 2 per row (last row has 1). Button text is the display name; `callback_data` is `dept:<tag>` (for example `dept:Sweng`). Cancel row at the bottom.
- On press: validate the tag, save `dept_tag`, edit message to `Department: <display name>\n\nChoose the year:` with the year keyboard. State: `Upload.year`.

**Step 2: year** (state `Upload.year`)
- Keyboard: one row with 1 to 5, `callback_data` `year:<n>`. Cancel row.
- On press: validate, save `year`, edit to `Department: ...\nYear: <n>\n\nChoose the semester:`. State: `Upload.semester`.

**Step 3: semester** (state `Upload.semester`)
- Keyboard: one row with 1 and 2, `callback_data` `sem:<n>`. Cancel row.
- On press: validate, save `semester`, edit to `Department: ...\nYear: ...\nSemester: <n>\n\nChoose the resource type:`. State: `Upload.type`.

**Step 4: type** (state `Upload.type`)
- Keyboard: 5 buttons from `data.TYPES`, 2 per row, `callback_data` `type:<code>` with codes `mid`, `final`, `ppt`, `reference`, `module`. Cancel row.
- On press: validate against `TYPES_BY_CODE`, save `type_code`, edit to `Department: ...\nYear: ...\nSemester: ...\nType: <label>\n\nType the course name (for example: Data Structures):` with a Cancel button only. State: `Upload.course_name`.

**Step 5: course name** (state `Upload.course_name`)
- The student types text. Clean it (strip, collapse repeated whitespace). Valid length: 2 to `MAX_COURSE_NAME_LENGTH` (100) characters. If invalid, reply with a short hint and stay in the state; delete the hint messages when practical.
- Best-effort delete the student's typed message (ignore any error) so the chat stays clean.
- Save `course`, edit the stored prompt message (by `prompt_msg_id`, via `edit_prompt`) into the summary. State: `Upload.confirm`.
- Non-text input: reply `Please type the course name as text.`

**Step 6: confirm** (state `Upload.confirm`)
- Message text:
  ```
  Please confirm:
  Department: Software Engineering
  Year: 3
  Semester: 1
  Type: Final Exam
  Course: Data Structures
  ```
- Buttons: `Confirm` (`confirm:yes`), `Edit course name` (`confirm:edit`), `Cancel` (`confirm:cancel`).
- `confirm:edit`: go back to the Step 4 course-name prompt, state `Upload.course_name`; after the new name the summary is shown again.
- `confirm:cancel`: same as the Cancel button.
- `confirm:yes`: go to Step 7.

**Step 7: upload** (state `Upload.uploading`)
- Edit message to: `Send your file(s). Please send them as File (not compressed photos) to keep the quality.\nTap Done when finished.\n\nFiles received: 0` with `Done` (`done`) and `Cancel` (`cancel`).
- Initialise `file_msg_ids = []`.
- Accept `document`, `photo`, `video`, `audio` messages. For each, append `message.message_id`. Beyond `MAX_FILES_PER_SESSION`, reject with a short reply.
- Update the counter by editing the prompt message text (`Files received: N`). Albums arrive as many messages within a second, so ignore `message is not modified` errors and any edit failure; consider debouncing the edit. The counter must never block collecting files.
- Do **not** download files. The bot only needs message ids to copy them.

**Step 8: Done**
- No files: `callback.answer("No files yet. Send at least one file.", show_alert=True)`; stay in state.
- If `sending` is already `True` (double tap): `callback.answer("Already sending...")` and return.
- Otherwise set `sending=True`, build the caption, copy the files (section 9), edit the message to `Sent X of Y file(s). Thank you!\nSend /start to add another resource.`, clear the state.

**Cancel** (button `cancel` or `/cancel`, in any state): clear the session, text `Cancelled. Send /start to begin again.`

## 8. Caption format

```
#Sweng #Y3 #S1 #FinalExam
Course: Data Structures
From: @username
```

- Line 1: department tag, `Y<year>`, `S<semester>`, type hashtag label (`MidExam`, `FinalExam`, `PPT`, `Reference`, `Module`). Hashtags only for the button-based fields.
- Line 2: the course name as typed, not as a hashtag (free text makes unreliable hashtags).
- Line 3 only when `INCLUDE_UPLOADER` is true: `@username`, or the numeric user id when there is no username.
- The same caption goes on every file of the batch so each one is searchable by hashtag.
- Stay under 1024 characters (guaranteed by the 100-character course limit; still assert it).

## 9. Posting to the channel

For each collected message id, in order:

```python
await bot.copy_message(
    chat_id=CHANNEL_ID,
    from_chat_id=user_chat_id,
    message_id=mid,
    caption=caption,
)
await asyncio.sleep(SEND_DELAY_SECONDS)
```

- Use `copy_message`, not `forward_message`, so there is no "forwarded from" header and the caption can be replaced.
- `copy_messages` (plural) cannot set captions; do not use it.
- `TelegramRetryAfter`: sleep `e.retry_after` seconds and retry the same file.
- `TelegramBadRequest` (for example the student deleted the message): log, count as failed, continue with the others.
- Return `(sent, failed)` and show both to the student. Since nothing is downloaded, Telegram's 20 MB bot download limit does not apply to copying.
- Albums are copied as individual files (grouping is lost). That is acceptable.

## 10. Edge cases and error handling

- `/start` or `/cancel` at any point resets the session (register these handlers first).
- Typed text while a button step is active: `Please use the buttons above.`
- Callback from an old menu (bot restarted, session lost): `This menu has expired. Send /start to begin again.` (alert).
- A button press that does not match the current state is ignored by the state filters and ends up in the stale-callback fallback.
- The bot must not crash on any update; log unexpected exceptions and keep polling.
- Log each completed upload: user id, tags, sent and failed counts. Never log the token.

## 11. aiogram implementation notes

- Handler order matters within a router: commands, then the cancel button, then state-specific handlers, then the fallbacks (already laid out in `handlers.py`).
- `callback_data` is limited to 64 bytes; the formats above are far below that.
- FSM data keys: `dept_tag`, `year`, `semester`, `type_code`, `course`, `prompt_msg_id`, `file_msg_ids`, `sending`.
- `callback.message` can be an inaccessible message type for very old messages; wrap edits in try/except `TelegramBadRequest`.
- Keep all user-visible texts as constants at the top of `handlers.py` so they are easy to change.

## 12. Test checklist

Walk through each path manually with a real bot and the channel:

1. Happy path: every step, 3 files (one as document, one as photo, one as video), Done. Check 3 posts with the correct caption in the channel.
2. Edit course name from the summary, confirm the summary updates.
3. Cancel at each step (button) and via `/cancel`.
4. Done with zero files.
5. Double tap on Done.
6. Send an album of 10 photos; check all 10 are counted and posted.
7. Restart the bot mid-flow, press an old button, check the expired-menu message.
8. Course name too short, too long, and non-text (sticker).
9. A user without a username (check the `From:` fallback).
10. Student deletes a file before pressing Done (failed count reported).

## 13. Definition of done

- All checklist items above pass.
- No `NotImplementedError` left in the code.
- Token and channel id come only from the environment.
- `python bot.py` runs without warnings on a clean virtualenv.

## 14. Open decisions (current defaults)

- **Uploader attribution** in the caption: default on, via `INCLUDE_UPLOADER`. The owner may want to tell students about it in the welcome text or switch it off.
- **Back buttons**: not in v1, only Cancel.
- **Session timeout**: none in v1.
- **Course name normalisation**: stored as typed; cleanup is left for the later reorganisation.
- **Hosting**: not decided (any VPS or free host running `python bot.py` under `systemd`, `pm2` or Docker).

## 15. Security

- Treat the bot token as a password. If it was ever pasted anywhere public or into a chat, revoke it in @BotFather (`/revoke`) and use the new one.
- Keep the channel private. The bot needs only the "Post messages" admin right.
