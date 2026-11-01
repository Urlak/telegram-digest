import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from src.timeutil import TimezoneConfigError, resolve_timezone

# Load environment variables from .env file
load_dotenv()


class ConfigError(ValueError):
    """Raised when an environment-backed configuration value is invalid."""


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ConfigError(f"{name} must be an integer, got '{raw}'.") from exc

    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}.")
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise ConfigError(f"{name} must be a number, got '{raw}'.") from exc

    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}.")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration container loaded from environment properties."""

    tg_api_id: int
    tg_api_hash: str
    tg_phone_number: str | None
    tg_bot_token: str
    gemini_api_key: str
    target_group: str
    message_limit: int
    hours_back: int
    export_only: bool
    max_llm_messages: int
    max_fetch_limit: int
    session_path: str

    # Added fields have defaults so existing call sites and tests keep working.
    timezone: str = ""
    max_llm_chars: int = 60000
    max_block_chars: int = 4000
    gemini_timeout_seconds: float = 120.0
    telegram_timeout_seconds: float = 60.0
    request_retries: int = 2
    max_flood_wait_seconds: int = 300


def load_config() -> AppConfig:
    """Loads environment variables into an AppConfig instance with default fallbacks.

    Returns:
        Populated immutable AppConfig dataclass.

    Raises:
        ConfigError: If a numeric value cannot be parsed or is negative.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")

    message_limit = _env_int("MESSAGE_LIMIT", 100, 1)
    # Keep the historical hard ceiling: a single Telegram batch is not useful
    # beyond this size and accidental huge values would only stall the bot.
    message_limit = min(message_limit, 10000)

    return AppConfig(
        tg_api_id=_env_int("TG_API_ID", 0, 0),
        tg_api_hash=os.getenv("TG_API_HASH", "").strip(),
        tg_phone_number=(os.getenv("TG_PHONE_NUMBER") or "").strip() or None,
        tg_bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        target_group=os.getenv("TARGET_GROUP", "").strip(),
        message_limit=message_limit,
        hours_back=_env_int("HOURS_BACK", 24, 1),
        export_only=_env_bool("EXPORT_ONLY", False),
        max_llm_messages=_env_int("MAX_LLM_MESSAGES", 500, 1),
        max_fetch_limit=_env_int("MAX_FETCH_LIMIT", 10000, 1),
        session_path=os.path.join(data_dir, "session"),
        timezone=os.getenv("TIMEZONE", "").strip(),
        max_llm_chars=_env_int("MAX_LLM_CHARS", 60000, 1000),
        max_block_chars=_env_int("MAX_BLOCK_CHARS", 4000, 100),
        gemini_timeout_seconds=_env_float("GEMINI_TIMEOUT_SECONDS", 120.0, 1.0),
        telegram_timeout_seconds=_env_float("TELEGRAM_TIMEOUT_SECONDS", 60.0, 1.0),
        request_retries=_env_int("REQUEST_RETRIES", 2, 0),
        max_flood_wait_seconds=_env_int("MAX_FLOOD_WAIT_SECONDS", 300, 1),
    )


def validate_config(
    config: AppConfig,
    *,
    require_bot: bool = False,
    require_gemini: bool = True,
) -> None:
    """Validates credentials and numeric limits for an entrypoint.

    ``load_config`` itself stays lenient about credentials so importing the
    module (and running unit tests) does not require a real environment.
    Entrypoints call this function once and fail fast with a clear message.

    Raises:
        ConfigError: If a required value is missing or out of range.
    """
    if config.tg_api_id <= 0:
        raise ConfigError("TG_API_ID must be a positive integer.")
    if not config.tg_api_hash:
        raise ConfigError("TG_API_HASH is required.")
    if require_bot and not config.tg_bot_token:
        raise ConfigError("TG_BOT_TOKEN is required to run the bot/API service.")
    if require_gemini and not config.export_only and not config.gemini_api_key:
        raise ConfigError("GEMINI_API_KEY is required unless EXPORT_ONLY=True.")

    if config.message_limit < 1:
        raise ConfigError("MESSAGE_LIMIT must be >= 1.")
    if config.hours_back < 1:
        raise ConfigError("HOURS_BACK must be >= 1.")
    if config.max_llm_messages < 1:
        raise ConfigError("MAX_LLM_MESSAGES must be >= 1.")
    if config.max_fetch_limit < 1:
        raise ConfigError("MAX_FETCH_LIMIT must be >= 1.")
    if config.max_block_chars < 1:
        raise ConfigError("MAX_BLOCK_CHARS must be >= 1.")
    if config.max_llm_chars < 1:
        raise ConfigError("MAX_LLM_CHARS must be >= 1.")
    if config.max_llm_chars < config.max_block_chars:
        raise ConfigError("MAX_LLM_CHARS must be >= MAX_BLOCK_CHARS.")
    if config.gemini_timeout_seconds <= 0:
        raise ConfigError("GEMINI_TIMEOUT_SECONDS must be > 0.")
    if config.telegram_timeout_seconds <= 0:
        raise ConfigError("TELEGRAM_TIMEOUT_SECONDS must be > 0.")
    if config.request_retries < 0:
        raise ConfigError("REQUEST_RETRIES must be >= 0.")
    if config.max_flood_wait_seconds < 1:
        raise ConfigError("MAX_FLOOD_WAIT_SECONDS must be >= 1.")

    if config.timezone:
        try:
            resolve_timezone(config.timezone)
        except TimezoneConfigError as exc:
            raise ConfigError(str(exc)) from exc


# Legacy module-level aliases maintained for backwards compatibility
_config = load_config()
TG_API_ID = _config.tg_api_id
TG_API_HASH = _config.tg_api_hash
TG_PHONE_NUMBER = _config.tg_phone_number
GEMINI_API_KEY = _config.gemini_api_key
TARGET_GROUP = _config.target_group
MESSAGE_LIMIT = _config.message_limit
HOURS_BACK = _config.hours_back
EXPORT_ONLY = _config.export_only
MAX_FETCH_LIMIT = _config.max_fetch_limit
MAX_LLM_MESSAGES = _config.max_llm_messages
TIMEZONE = _config.timezone
MAX_LLM_CHARS = _config.max_llm_chars
MAX_BLOCK_CHARS = _config.max_block_chars


def setup_logging():
    """Configures structured stderr logging across application and Uvicorn loggers.

    Notes:
        Overrides Uvicorn handler list to ensure uniform log formatting in Docker containers.
        Long records (Telethon logs raw TL byte dumps) are truncated so one failure
        cannot flood the container log.
    """
    import sys
    import logging

    class _TruncateBlobs(logging.Filter):
        """Cuts pathological single-record payloads such as binary dumps."""

        limit = 2000

        def filter(self, record: logging.LogRecord) -> bool:
            message = record.getMessage()
            if len(message) > self.limit:
                record.msg = message[: self.limit] + "... [truncated]"
                record.args = ()
            return True

    class _DropHealthNoise(logging.Filter):
        """Drops successful /health probes: the Docker healthcheck hits them every 30s."""

        def filter(self, record: logging.LogRecord) -> bool:
            if record.name != "uvicorn.access":
                return True
            message = record.getMessage()
            return not ("/health" in message and message.rstrip().endswith(" 200"))

    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    handler.addFilter(_TruncateBlobs())
    handler.addFilter(_DropHealthNoise())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = [handler]

    # Align Uvicorn logging handlers with application root logger
    for uvicorn_logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        u_logger = logging.getLogger(uvicorn_logger_name)
        u_logger.handlers = [handler]
        u_logger.propagate = False
