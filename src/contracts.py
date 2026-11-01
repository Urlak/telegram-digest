"""Shared data contracts for the digest pipeline.

The project historically passed plain dictionaries between modules.  These
dataclasses make the *boundaries* explicit (what was fetched, what was sent to
the LLM, what metadata a report carries) without changing the message payload
shape used by the formatters and tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FetchOutcome:
    """Result of one Telegram fetch attempt.

    ``mode`` is one of:

    * ``unread``   -- oldest unread batch was requested (safe to acknowledge),
    * ``fallback`` -- no unread messages, recent history was requested,
    * ``none``     -- nothing was requested.
    """

    messages: list[dict] = field(default_factory=list)
    mode: str = "none"
    scanned_count: int = 0
    age_skipped: int = 0
    filter_skipped: int = 0
    unread_count: int = 0
    remaining_unread: int = 0

    # Ascending Telegram message IDs that were actually scanned, and the subset
    # that passed the quality filters.  Both are used to compute a safe
    # contiguous read-acknowledgement boundary.
    scanned_ids: list[int] = field(default_factory=list)
    parsed_ids: set[int] = field(default_factory=set)

    incomplete: bool = False
    error: str | None = None
    batch_max_id: int | None = None
    oldest_unread_id: int | None = None

    @property
    def parsed_count(self) -> int:
        return len(self.messages)


@dataclass
class SummaryResult:
    """Result of one Gemini summarization call."""

    text: str
    api_duration: float = 0.0
    model: str = ""
    used_count: int = 0
    used_chars: int = 0
    total_count: int = 0
    truncated: bool = False
    used_message_ids: set[int] = field(default_factory=set)


@dataclass
class ReportMetadata:
    """Everything the report footer needs to be honest about its input."""

    group_name: str
    group_id: str
    generated_at: str = ""
    period_start: str | None = None
    period_end: str | None = None
    model: str = ""
    timezone: str = ""
    source_message_count: int = 0
    collapsed_block_count: int = 0
    llm_message_count: int = 0
    llm_char_count: int = 0
    truncated: bool = False
    api_duration: float = 0.0
    unread_count: int = 0
    remaining_unread: int = 0
    fetch_mode: str = ""
    incomplete: bool = False
    acknowledged: bool = False
    acknowledged_max_id: int | None = None
    config_hours_back: int | None = None
