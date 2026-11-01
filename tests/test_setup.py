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


def test_setup_logging_drops_successful_health_probes(capsys):
    """Healthcheck chatter is hidden without losing failing probes or real traffic."""
    setup_logging()
    access = logging.getLogger("uvicorn.access")

    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/health", "1.1", 200)
    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:2", "GET", "/health", "1.1", 503)
    access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:3", "GET", "/start", "1.1", 200)

    err = capsys.readouterr().err
    assert '"GET /health HTTP/1.1" 200' not in err
    assert '"GET /health HTTP/1.1" 503' in err
    assert '"GET /start HTTP/1.1" 200' in err
