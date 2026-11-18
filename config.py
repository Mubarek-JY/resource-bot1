"""Configuration loaded from environment variables (see .env.example).

Never hardcode the token or channel id anywhere else in the code.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"Missing required environment variable: {name} (see .env.example)")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


BOT_TOKEN: str = _require("BOT_TOKEN")

# Bot API channel ids look like -100xxxxxxxxxx (note the -100 prefix).
CHANNEL_ID: int = int(_require("CHANNEL_ID"))

# Telegram user id to receive operational alerts; unset disables alerts.
ADMIN_ID: int | None = int(os.getenv("ADMIN_ID", "").strip() or 0) or None

# Put "From: @username" (or the numeric user id) in the channel caption.
INCLUDE_UPLOADER: bool = _bool("INCLUDE_UPLOADER", True)

# Safety cap on files accepted in one upload session.
MAX_FILES_PER_SESSION: int = int(os.getenv("MAX_FILES_PER_SESSION", "30"))

# Pause between copy_message calls to stay under Telegram's posting limits
# (about 20 messages per minute into one chat).
SEND_DELAY_SECONDS: float = float(os.getenv("SEND_DELAY_SECONDS", "3"))

# Maximum length of the typed course name.
MAX_COURSE_NAME_LENGTH: int = 100
