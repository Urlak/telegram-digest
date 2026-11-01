from src.telegram_format import (
    markdown_to_telegram_html,
    split_html,
    utf16_len,
)


def test_escapes_html_and_converts_bold():
    result = markdown_to_telegram_html("Use <tag> & **bold**")
    assert "&lt;tag&gt;" in result
    assert "&amp;" in result
    assert "<b>bold</b>" in result


def test_headings_lists_and_blockquotes():
    result = markdown_to_telegram_html(
        "## Главное\n\n- Первый\n- Второй\n\n> Цитата"
    )

    assert "<b>Главное</b>" in result
    assert "• Первый" in result
    assert "• Второй" in result
    assert "<blockquote>Цитата</blockquote>" in result


def test_code_blocks_are_preserved_and_escaped():
    result = markdown_to_telegram_html(
        "```python\nif a < b:\n    print('x')\n```"
    )

    assert "<pre><code>" in result
    assert "if a &lt; b:" in result
    assert "    print('x')" in result


def test_inline_code_is_not_formatted():
    result = markdown_to_telegram_html("Use `**not bold**` here")
    assert "<code>**not bold**</code>" in result
    assert "<b>" not in result


def test_markdown_link_becomes_anchor():
    result = markdown_to_telegram_html("[example](https://example.com/a?x=1&y=2)")
    assert '<a href="https://example.com/a?x=1&amp;y=2">example</a>' in result


def test_split_html_returns_single_short_chunk():
    assert split_html("hello") == ["hello"]
    assert split_html("") == []


def test_split_html_never_exceeds_limit_and_balances_tags():
    text = "<b>" + ("word " * 2000) + "</b>"
    chunks = split_html(text, limit=500)

    assert len(chunks) > 1
    assert all(utf16_len(chunk) <= 500 for chunk in chunks)
    assert all(chunk.strip() for chunk in chunks)
    assert all(chunk.count("<b>") == chunk.count("</b>") for chunk in chunks)


def test_split_html_prefers_paragraph_boundaries():
    text = "\n\n".join(f"Paragraph {index}" for index in range(200))
    chunks = split_html(text, limit=300)

    assert len(chunks) > 1
    assert all(utf16_len(chunk) <= 300 for chunk in chunks)


def test_utf16_length_counts_emoji_as_two_units():
    assert utf16_len("a") == 1
    assert utf16_len("😀") == 2
