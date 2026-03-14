import os
import sqlite3
import pytest

from src.db import init_db

def test_db_initialization(tmp_path):
    """Validate that the application DB structure builds out cleanly."""
    db_file = tmp_path / "test.db"
    
    # Initialize DB schema
    init_db(str(db_file))
    assert os.path.exists(db_file), "Database file was not created."

    # Verify table existence
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='processed_messages'")
    table = cursor.fetchone()
    
    assert table is not None, "'processed_messages' table was not found."
    conn.close()

def test_gemini_library_import():
    """
    Validates google-generativeai isn't erroring out contextually
    (similar to an issue spotted in previous project runs).
    """
    try:
        import google.generativeai as genai
    except ImportError as e:
        pytest.fail(f"Could not load Google Generative AI package: {e}")
