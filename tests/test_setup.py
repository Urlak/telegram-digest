import pytest

def test_gemini_library_import():
    """
    Validates google-generativeai isn't erroring out contextually
    (similar to an issue spotted in previous project runs).
    """
    try:
        import google.generativeai as genai
    except ImportError as e:
        pytest.fail(f"Could not load Google Generative AI package: {e}")
