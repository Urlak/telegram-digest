import os
import logging
from dotenv import load_dotenv
from dataclasses import dataclass

# Load environment variables from .env file
load_dotenv()

@dataclass(frozen=True)
class AppConfig:
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

def load_config() -> AppConfig:
    """Loads configuration from environment and defines standard paths."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')
    
    return AppConfig(
        tg_api_id=int(os.getenv("TG_API_ID", "0")),
        tg_api_hash=os.getenv("TG_API_HASH", ""),
        tg_phone_number=os.getenv("TG_PHONE_NUMBER"),
        tg_bot_token=os.getenv("TG_BOT_TOKEN", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        target_group=os.getenv('TARGET_GROUP', '').strip(),
        message_limit=min(int(os.getenv('MESSAGE_LIMIT', '100')), 10000),
        hours_back=int(os.getenv('HOURS_BACK', '24')),
        export_only=os.getenv('EXPORT_ONLY', 'False').lower() == 'true',
        max_llm_messages=int(os.getenv('MAX_LLM_MESSAGES', '500')),
        max_fetch_limit=10000,
        session_path=os.path.join(data_dir, 'session')
    )

# Legacy support for module-level variables (will be phased out in Phase 3)
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

def setup_logging():
    """
    Sets up basic logging to stdout. 
    This is useful for Docker Container Manager to capture logs.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )
