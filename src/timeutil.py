"""Timezone helpers shared by message parsing, summaries and reports.

Telegram returns naive/UTC datetimes.  The digest is meant to be read by a
human, so every user-facing timestamp is converted to an explicit local
timezone (``TIMEZONE`` when configured, otherwise the system timezone).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimezoneConfigError(ValueError):
    """Raised when a configured timezone name cannot be resolved."""


def resolve_timezone(name: str | None) -> tuple[tzinfo, str]:
    """Resolves a timezone name into a ``tzinfo`` and a human readable label.

    Args:
        name: IANA timezone name (for example ``Europe/Moscow``).  Empty or
            ``None`` means "use the system local timezone".

    Returns:
        Tuple of ``(tzinfo, label)``.  ``label`` is the IANA key when one was
        configured, otherwise the system timezone name (or its string form).
    """
    if name and name.strip():
        key = name.strip()
        try:
            return ZoneInfo(key), key
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise TimezoneConfigError(
                f"TIMEZONE='{key}' is not a valid IANA timezone name."
            ) from exc

    local = datetime.now().astimezone().tzinfo or timezone.utc
    label = getattr(local, "key", None) or str(local)
    return local, label


def ensure_utc(value: datetime) -> datetime:
    """Returns ``value`` as an aware UTC datetime, assuming UTC when naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local(value: datetime, tz: tzinfo) -> datetime:
    """Converts a UTC (or naive-UTC) datetime into the target timezone."""
    return ensure_utc(value).astimezone(tz)


def offset_label(value: datetime) -> str:
    """Formats the UTC offset of an aware datetime as ``+03:00``."""
    offset = value.utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def format_local(value: datetime, tz: tzinfo) -> str:
    """Formats a datetime as ``YYYY-MM-DD HH:MM`` in the target timezone."""
    return to_local(value, tz).strftime("%Y-%m-%d %H:%M")


def format_local_full(value: datetime, tz: tzinfo) -> str:
    """Formats a datetime as ``YYYY-MM-DD HH:MM:SS +HH:MM``."""
    local = to_local(value, tz)
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} {offset_label(local)}"


def now_with_offset(tz: tzinfo, now: datetime | None = None) -> str:
    """Formats "now" for the prompt, including an explicit UTC offset."""
    current = (now or datetime.now(tz)).astimezone(tz)
    return f"{current.strftime('%Y-%m-%d %H:%M')} (UTC{offset_label(current)})"
