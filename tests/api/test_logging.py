import json
from pathlib import Path

from astraquant_api.logging import ActivityBuffer, configure_logging


def test_redacts_nested_sensitive_values(tmp_path: Path) -> None:
    activity = ActivityBuffer()
    logger = configure_logging(tmp_path, activity)

    logger.info(
        "runtime.started",
        session_token="secret-token",
        nested={"Authorization": "Bearer value", "safe": "visible"},
        password="hidden",
    )

    log_file = next(tmp_path.glob("*.jsonl"))
    record = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert record["session_token"] == "[REDACTED]"
    assert record["nested"]["Authorization"] == "[REDACTED]"
    assert record["nested"]["safe"] == "visible"
    assert record["password"] == "[REDACTED]"
    assert activity.list_items(limit=1)[0].event == "runtime.started"
