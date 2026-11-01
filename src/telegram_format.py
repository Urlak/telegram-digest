"""Markdown -> Telegram-safe HTML conversion and tag-aware splitting.

Telegram renders a small HTML subset (``b``, ``i``, ``u``, ``s``, ``code``,
``pre``, ``a``, ``blockquote``).  The digest is generated as Markdown, so it has
to be converted and escaped before sending.  Splitting is tag-aware: a chunk
never ends with unclosed formatting tags.
"""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)(?:\s[^<>]*)?>")
_OPEN_TAGS = {"b", "i", "u", "s", "code", "pre", "a", "blockquote"}


def utf16_len(value: str) -> int:
    """Returns the UTF-16 code-unit length used by Telegram's limit."""
    return len(value.encode("utf-16-le")) // 2


def markdown_to_telegram_html(text: str) -> str:
    """Converts a Markdown digest into Telegram's HTML subset.

    Unsupported constructs are degraded gracefully: headings become bold text,
    lists become bullets, and horizontal rules become a plain line.  All literal
    ``&``, ``<`` and ``>`` characters are escaped.
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    placeholders: dict[str, str] = {}

    def _stash(rendered: str) -> str:
        key = f"\x00{len(placeholders)}\x00"
        placeholders[key] = rendered
        return key

    def _fenced(match: re.Match) -> str:
        code = match.group(2).rstrip("\n")
        return _stash(f"<pre><code>{html.escape(code, quote=False)}</code></pre>")

    def _inline_code(match: re.Match) -> str:
        return _stash(f"<code>{html.escape(match.group(1), quote=False)}</code>")

    # Protect code before escaping/formatting the rest.
    text = re.sub(r"```([^\n`]*)\n(.*?)```", _fenced, text, flags=re.DOTALL)
    text = re.sub(r"`([^`\n]+)`", _inline_code, text)

    text = html.escape(text, quote=False)

    # Links first: the URL and label are already escaped.
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # Bold, italic, strikethrough.  These stay line-scoped on purpose: a
    # stray bullet ``*`` must not swallow the rest of the digest.
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)__(.+?)__(?!\w)", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    lines: list[str] = []
    for line in text.split("\n"):
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if heading:
            lines.append(f"<b>{heading.group(1)}</b>")
        elif line.startswith("&gt; "):
            lines.append(f"<blockquote>{line[5:]}</blockquote>")
        elif re.match(r"^\s*[-*+]\s+", line):
            lines.append(re.sub(r"^(\s*)[-*+]\s+", r"\1• ", line))
        elif re.match(r"^\s*-{3,}\s*$", line):
            lines.append("──────────")
        else:
            lines.append(line)

    text = "\n".join(lines)

    for key, rendered in placeholders.items():
        text = text.replace(key, rendered)

    return text.strip()


def _balance_tags(chunk: str) -> tuple[str, str]:
    """Closes open tags at the end of ``chunk`` and returns reopen markup."""
    stack: list[tuple[str, str]] = []

    for match in _TAG_RE.finditer(chunk):
        raw = match.group(0)
        name = match.group(1).lower()
        if name not in _OPEN_TAGS:
            continue
        if raw.startswith("</"):
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == name:
                    del stack[index:]
                    break
        elif not raw.endswith("/>"):
            stack.append((name, raw))

    closing = "".join(f"</{name}>" for name, _ in reversed(stack))
    reopening = "".join(raw for _, raw in stack)
    return chunk + closing, reopening


def _safe_cut(text: str, limit: int) -> int:
    """Finds the largest prefix within the limit that does not split a tag."""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if utf16_len(text[:mid]) <= limit:
            low = mid
        else:
            high = mid - 1

    cut = max(low, 1)

    open_angle = text.rfind("<", 0, cut)
    close_angle = text.rfind(">", 0, cut)
    if open_angle > close_angle:
        cut = max(open_angle, 1)

    newline = text.rfind("\n", 0, cut)
    if newline > cut // 2:
        cut = newline + 1

    return max(cut, 1)


def _hard_split_html(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    rest = text

    while rest:
        if utf16_len(rest) <= limit:
            chunks.append(rest)
            break
        cut = _safe_cut(rest, limit)

        # Closing tags added by balancing must also fit into the chunk.
        while cut > 1:
            piece, reopening = _balance_tags(rest[:cut])
            if utf16_len(piece) <= limit:
                break
            cut -= 1

        piece, reopening = _balance_tags(rest[:cut])
        chunks.append(piece)
        rest = reopening + rest[cut:]

    return chunks


def _split_long_block(block: str, limit: int) -> list[str]:
    lines = block.split("\n")
    chunks: list[str] = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if utf16_len(candidate) <= limit:
            current = candidate
            continue

        if current:
            balanced, reopening = _balance_tags(current)
            chunks.append(balanced)
            current = reopening

        if utf16_len(line) > limit:
            hard = _hard_split_html(line, limit)
            chunks.extend(hard[:-1])
            current = hard[-1] if hard else ""
        else:
            current = f"{current}\n{line}" if current else line

    if current:
        chunks.append(current)

    return chunks


def _split_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []

    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current))

    # Keep a short heading attached to the paragraph that follows it.
    merged: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        is_heading = (
            block.startswith("<b>")
            and block.endswith("</b>")
            and "\n" not in block
            and len(block) < 160
        )
        if is_heading and index + 1 < len(blocks):
            merged.append(f"{block}\n\n{blocks[index + 1]}")
            index += 2
        else:
            merged.append(block)
            index += 1

    return merged


def split_html(text: str, limit: int = 3500) -> list[str]:
    """Splits Telegram HTML into chunks below ``limit`` UTF-16 units.

    Splits prefer paragraph boundaries, then line boundaries, and only fall back
    to a tag-aware character split for a single oversized line (for example a
    huge ``<pre>`` block).  Empty chunks are never returned.
    """
    if not text:
        return []
    if utf16_len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for block in _split_blocks(text):
        candidate = f"{current}\n\n{block}" if current else block
        if utf16_len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if utf16_len(block) <= limit:
            current = block
        else:
            pieces = _split_long_block(block, limit)
            chunks.extend(pieces[:-1])
            current = pieces[-1] if pieces else ""

    if current:
        chunks.append(current)

    # Final safety pass: never return an oversized chunk.
    final: list[str] = []
    for chunk in chunks:
        if utf16_len(chunk) <= limit:
            final.append(chunk)
        else:
            final.extend(_hard_split_html(chunk, limit))

    return [chunk for chunk in final if chunk.strip()]
