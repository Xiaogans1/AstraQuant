from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast

import structlog

_SENSITIVE_FRAGMENTS = ("token", "authorization", "password", "secret")


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    timestamp: str
    level: str
    event: str
    component: str | None
    correlation_id: str | None
    task_id: str | None


class ActivityBuffer:
    def __init__(self, capacity: int = 200) -> None:
        self._items: deque[ActivityRecord] = deque(maxlen=capacity)
        self._lock = Lock()

    def append(self, item: ActivityRecord) -> None:
        with self._lock:
            self._items.append(item)

    def list_items(self, *, limit: int = 100) -> list[ActivityRecord]:
        with self._lock:
            return list(reversed(self._items))[:limit]


def _is_sensitive(key: object) -> bool:
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def _redact(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if _is_sensitive(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _redact_processor(
    _logger: Any,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    return cast(structlog.types.EventDict, _redact(event_dict))


def _activity_processor(activity: ActivityBuffer) -> structlog.types.Processor:
    def capture(
        _logger: Any,
        method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        activity.append(
            ActivityRecord(
                timestamp=str(event_dict.get("timestamp", "")),
                level=str(event_dict.get("level", method_name)),
                event=str(event_dict.get("event", "")),
                component=_optional_string(event_dict.get("component")),
                correlation_id=_optional_string(event_dict.get("correlation_id")),
                task_id=_optional_string(event_dict.get("task_id")),
            )
        )
        return event_dict

    return capture


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def configure_logging(
    log_dir: Path,
    activity: ActivityBuffer,
) -> structlog.stdlib.BoundLogger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
    stream = log_path.open("a", encoding="utf-8", buffering=1)
    processors: list[structlog.types.Processor] = [
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        _redact_processor,
        _activity_processor(activity),
        structlog.processors.JSONRenderer(sort_keys=True),
    ]
    return cast(
        structlog.stdlib.BoundLogger,
        structlog.wrap_logger(
            structlog.PrintLogger(stream),
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
        ),
    )
