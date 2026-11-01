"""Pure text processing helpers: cleanup, link normalization and export formatting."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# A URL is detected with an explicit scheme or a bare ``www.``/``t.me/`` prefix.
_URL_RE = re.compile(
    r"(?:https?://|www\.|t\.me/)[^\s<>()\[\]{}\"']+",
    re.IGNORECASE,
)

# Fenced code blocks and inline code are protected from link/whitespace rewriting.
_PROTECTED_RE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)

_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")

# Hostname -> short platform marker.  The first matching suffix wins.
_PLATFORM_HOSTS: tuple[tuple[str, str], ...] = (
    ("youtube.com", "YT"),
    ("youtu.be", "YT"),
    ("t.me", "TG"),
    ("telegram.me", "TG"),
    ("telegram.dog", "TG"),
    ("instagram.com", "IG"),
    ("instagr.am", "IG"),
    ("facebook.com", "FB"),
    ("fb.com", "FB"),
    ("fb.watch", "FB"),
    ("tiktok.com", "TT"),
    ("x.com", "X"),
    ("twitter.com", "X"),
    ("t.co", "X"),
    ("reddit.com", "Reddit"),
    ("redd.it", "Reddit"),
    ("github.com", "GitHub"),
)

_TRAILING_URL_CHARS = ".,;:!?…»”\"'"


def format_duration(seconds: object) -> str:
    """Formats a media duration in seconds as ``M:SS`` or ``H:MM:SS``."""
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    total = max(total, 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def clean_text_basic(text: str | None) -> str:
    """Normalizes whitespace without destroying technical formatting.

    Fenced code blocks, indented code, lists and block quotes are preserved.
    Prose lines have internal runs of spaces collapsed and trailing whitespace
    removed; at most one blank line is kept between paragraphs.
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    result: list[str] = []
    in_fence = False
    previous_was_list = False
    previous_was_blank = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            result.append(line.rstrip())
            previous_was_list = False
            previous_was_blank = False
            continue

        if in_fence:
            # Keep code verbatim; only remove trailing spaces that editors add.
            result.append(line.rstrip())
            previous_was_blank = False
            continue

        indent = line[: len(line) - len(line.lstrip(" \t"))]
        body = line[len(indent) :]

        is_indented_code = len(indent.expandtabs(4)) >= 4
        is_continuation = bool(indent) and previous_was_list

        # Preserve internal spacing inside code and list continuations.  In
        # ordinary prose (and in the list marker itself) runs of spaces are
        # just sloppy input and are collapsed.
        if is_indented_code or is_continuation:
            body = body.rstrip()
        else:
            body = re.sub(r"[ \t]+", " ", body).rstrip()

        is_list = bool(_LIST_MARKER_RE.match(body))
        is_quote = body.startswith(">")

        # Preserve indentation only when it is structural.  A couple of leading
        # spaces in ordinary prose are just sloppy input and are stripped.
        preserve_indent = bool(indent) and (
            is_indented_code or is_list or is_quote or previous_was_list
        )

        if not body:
            if not previous_was_blank:
                result.append("")
            previous_was_blank = True
            previous_was_list = False
        else:
            result.append(f"{indent}{body}" if preserve_indent else body)
            previous_was_blank = False
            previous_was_list = is_list

    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()

    return "\n".join(result)


def _trim_url(url: str) -> str:
    """Removes sentence punctuation that the URL regex may have swallowed."""
    trimmed = url
    while trimmed and trimmed[-1] in _TRAILING_URL_CHARS:
        trimmed = trimmed[:-1]
    while trimmed.endswith(")") and trimmed.count("(") < trimmed.count(")"):
        trimmed = trimmed[:-1]
    return trimmed


def _host_of(url: str) -> str:
    candidate = url if "://" in url else f"http://{url}"
    try:
        return (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return ""


def _platform_for_host(host: str) -> str | None:
    host = host.lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    for domain, label in _PLATFORM_HOSTS:
        if host == domain or host.endswith(f".{domain}"):
            return label
    return None


def _normalize_links_in_line(line: str) -> str:
    matches = list(_URL_RE.finditer(line))
    if not matches:
        return line

    counts: dict[str, int] = {}
    positions: list[tuple[int, int, str]] = []

    for match in matches:
        raw = match.group(0)
        url = _trim_url(raw)
        if not url:
            continue
        end = match.start() + len(url)
        host = _host_of(url)
        label = _platform_for_host(host)
        key = label or f"Web: {host or 'unknown'}"
        counts[key] = counts.get(key, 0) + 1
        positions.append((match.start(), end, key))

    if not positions:
        return line

    pieces: list[str] = []
    cursor = 0
    emitted: set[str] = set()

    for start, end, key in positions:
        pieces.append(line[cursor:start])
        if key not in emitted:
            count = counts[key]
            pieces.append(f"[{key} ×{count}]" if count > 1 else f"[{key}]")
            emitted.add(key)
        cursor = end
    pieces.append(line[cursor:])

    result = "".join(pieces)
    # Collapse only spaces that were left behind by removed URLs.
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r" +\n", "\n", result)
    return result


def normalize_links(text: str | None) -> str:
    """Replaces full URLs with compact platform markers.

    Links inside fenced/inline code are preserved.  Unknown hosts become
    ``[Web: domain.com]`` and repeated markers get a ``×N`` counter.
    Nothing is fetched from the network.
    """
    if not text:
        return ""

    segments: list[str] = []
    cursor = 0
    for match in _PROTECTED_RE.finditer(text):
        if match.start() > cursor:
            segments.append(
                "\n".join(
                    _normalize_links_in_line(line)
                    for line in text[cursor : match.start()].split("\n")
                )
            )
        segments.append(match.group(0))
        cursor = match.end()

    if cursor < len(text):
        segments.append(
            "\n".join(
                _normalize_links_in_line(line) for line in text[cursor:].split("\n")
            )
        )

    return "".join(segments)


def _sort_key(message: dict) -> tuple[float, int]:
    timestamp = message.get("timestamp")
    try:
        time_value = float(timestamp)
    except (TypeError, ValueError):
        time_value = 0.0
    message_id = message.get("message_id")
    try:
        id_value = int(message_id)
    except (TypeError, ValueError):
        id_value = 0
    return time_value, id_value


def format_messages_to_markdown(
    messages: list[dict], group_name: str, group_id: str
) -> str:
    """Formats original Telegram messages into a readable Markdown log.

    This is used by ``EXPORT_ONLY`` and deliberately keeps individual message
    IDs, authors, local timestamps, reply links, media markers and the original
    (un-normalized) text including full URLs.
    """
    md_content = f"# SOURCE: {group_name} (ID: {group_id})\n---\n"

    current_date = None
    for message in sorted(messages, key=_sort_key):
        date_value = message.get("date") or ""
        msg_date = date_value[:10]
        msg_time = date_value[11:16] if len(date_value) >= 16 else date_value

        if msg_date and msg_date != current_date:
            current_date = msg_date
            md_content += f"\n## DATE: {current_date}\n\n"

        text = message.get("raw_text")
        if text is None:
            text = message.get("text") or ""
        if message.get("media") and message.get("media") not in text:
            text = f"{message['media']}\n{text}".strip()

        reply_info = (
            f" (reply to {message['reply_to_id']})"
            if message.get("reply_to_id")
            else ""
        )
        md_content += (
            f"**[[{msg_time}]] [ID:[{message['message_id']}]] "
            f"[{message['sender_name']}]**{reply_info}: {text}\n"
        )

    md_content += "\n\n"
    return md_content
