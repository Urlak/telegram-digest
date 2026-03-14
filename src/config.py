import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Configuration
TG_API_ID = os.getenv("TG_API_ID")
TG_API_HASH = os.getenv("TG_API_HASH")
TG_PHONE_NUMBER = os.getenv("TG_PHONE_NUMBER")

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Extraction Options
TARGET_GROUPS = os.getenv("TARGET_GROUPS", "")
MESSAGE_LIMIT = int(os.getenv("MESSAGE_LIMIT", "100"))
HOURS_BACK = int(os.getenv("HOURS_BACK", "24"))

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
