"""Append-only event log for staging → merge → agent handoffs."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.orchestration.paths import get_events_dir


@dataclass
class Event:
    event_id: str
    type: str
    run_id: str | None
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> Event:
        data = json.loads(line)
        return cls(
            event_id=data["event_id"],
            type=data["type"],
            run_id=data.get("run_id"),
            timestamp=data["timestamp"],
            payload=data.get("payload", {}),
        )


def event_log_path() -> Path:
    return get_events_dir() / "event_log.jsonl"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def emit_event(
    event_type: str,
    *,
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
    log_path: Path | None = None,
) -> Event:
    """Append an event to the log and return it."""
    path = log_path or event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    event = Event(
        event_id=str(uuid.uuid4()),
        type=event_type,
        run_id=run_id,
        timestamp=_utc_now(),
        payload=payload or {},
    )

    with path.open("a", encoding="utf-8") as handle:
        handle.write(event.to_json_line() + "\n")

    return event


def read_all_events(log_path: Path | None = None) -> list[Event]:
    path = log_path or event_log_path()
    if not path.exists():
        return []

    events: list[Event] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(Event.from_json_line(line))
        except (json.JSONDecodeError, KeyError):
            continue
    return events


def read_events_since(
    after_event_id: str | None = None,
    *,
    event_types: set[str] | None = None,
    run_id: str | None = None,
    log_path: Path | None = None,
) -> list[Event]:
    """Return events after ``after_event_id`` (exclusive), optionally filtered."""
    events = read_all_events(log_path)
    if after_event_id:
        ids = [event.event_id for event in events]
        if after_event_id in ids:
            start = ids.index(after_event_id) + 1
            events = events[start:]

    if run_id is not None:
        events = [event for event in events if event.run_id == run_id]

    if event_types is not None:
        events = [event for event in events if event.type in event_types]

    return events


def latest_event_id(log_path: Path | None = None) -> str | None:
    events = read_all_events(log_path)
    if not events:
        return None
    return events[-1].event_id
