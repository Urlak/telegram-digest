import logging
import sys

import pytest

from src.config import setup_logging


def test_gemini_library_import():
    """
    Validates google-generativeai isn't erroring out contextually
    (similar to an issue spotted in previous project runs).
    """
    try:
        import google.generativeai as genai
    except ImportError as e:
        pytest.fail(f"Could not load Google Generative AI package: {e}")


def test_setup_logging_uses_stderr_for_all_levels():
    """Logging should bypass stdout buffering by sending records to stderr."""
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    setup_logging()

    handlers = root_logger.handlers
    assert handlers, "setup_logging should install at least one handler"
    assert any(isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr for handler in handlers)
    assert not any(isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout for handler in handlers)
