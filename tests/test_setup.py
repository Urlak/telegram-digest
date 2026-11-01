import logging
import sys

import pytest

from src.config import setup_logging


def test_gemini_library_import():
    """Validates that the active google-genai SDK can be imported."""
    try:
        from google import genai  # noqa: F401
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


def test_setup_logging_truncates_binary_blobs(capsys):
    """A single Telethon byte dump must not flood the container log."""
    setup_logging()

    logging.getLogger("telethon.network.mtprotosender").error(
        "Remaining bytes: b'%s'", "\\x1f" * 4000
    )

    captured = capsys.readouterr()
    assert "[truncated]" in captured.err
    longest = max(captured.err.splitlines(), key=len)
    assert len(longest) < 2500, len(longest)
