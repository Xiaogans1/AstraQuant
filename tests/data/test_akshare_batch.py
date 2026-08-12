from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from astraquant_data.akshare_batch import AkShareFiveMinuteBatchCollector
from astraquant_data.evidence import EvidenceClass, EvidenceGate, FormalAdmissionError
from astraquant_data.providers import HistoryRequest
from astraquant_domain import Adjustment, Bar, BarFrequency, InstrumentId, RunClass

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeProvider:
    def __init__(self, *, fail_once: set[str] | None = None, always_fail: set[str] | None = None):
        self.calls: list[str] = []
        self.fail_once = set(fail_once or ())
        self.always_fail = set(always_fail or ())

    def fetch_bars(self, request: HistoryRequest) -> tuple[Bar, ...]:
        key = str(request.instrument_id)
        self.calls.append(key)
        if key in self.always_fail:
            raise TimeoutError("upstream timeout")
        if key in self.fail_once:
            self.fail_once.remove(key)
            raise TimeoutError("transient")
        event_time = datetime.combine(request.start, datetime.min.time(), SHANGHAI) + timedelta(
            hours=9, minutes=35
        )
        return (
            Bar(
                instrument_id=request.instrument_id,
                frequency=BarFrequency.FIVE_MINUTE,
                trading_date=request.start,
                event_time=event_time,
                available_time=event_time + timedelta(minutes=1),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=Decimal("10000"),
                turnover=Decimal("105000"),
                open_interest=None,
                settlement=None,
                adjustment=Adjustment.NONE,
                availability_estimated=True,
            ),
        )


def test_batch_retries_checkpoints_and_resumes_without_refetch(tmp_path: Path) -> None:
    instruments = (
        InstrumentId.parse("600000.SSE"),
        InstrumentId.parse("000001.SZSE"),
    )
    provider = FakeProvider(fail_once={"600000.SSE"})
    sleeps: list[float] = []
    collector = AkShareFiveMinuteBatchCollector(
        provider=provider,
        checkpoint_path=tmp_path / "checkpoint",
        max_workers=2,
        max_attempts=2,
        backoff_seconds=0.25,
        sleep=sleeps.append,
    )

    first = collector.collect(instruments=instruments, trading_date=date(2026, 7, 24))
    calls_after_first = list(provider.calls)
    second = collector.collect(instruments=instruments, trading_date=date(2026, 7, 24))

    assert len(first.bars) == 2
    assert first.failures == ()
    assert sleeps == [0.25]
    assert provider.calls == calls_after_first
    assert second.resumed == tuple(sorted(instruments, key=str))
    assert second.evidence.evidence_class is EvidenceClass.EXPLORATORY_ONLY
    summary = json.loads((tmp_path / "checkpoint" / "summary.json").read_text())
    assert summary["evidence_class"] == "EXPLORATORY_ONLY"
    assert summary["row_count"] == 2


def test_batch_records_failures_and_resume_recovers_only_missing_item(tmp_path: Path) -> None:
    failed = InstrumentId.parse("600000.SSE")
    succeeded = InstrumentId.parse("000001.SZSE")
    provider = FakeProvider(always_fail={str(failed)})
    collector = AkShareFiveMinuteBatchCollector(
        provider=provider,
        checkpoint_path=tmp_path / "checkpoint",
        max_attempts=1,
    )

    first = collector.collect(instruments=(failed, succeeded), trading_date=date(2026, 7, 24))
    provider.always_fail.clear()
    second = collector.collect(instruments=(failed, succeeded), trading_date=date(2026, 7, 24))

    assert [item.instrument_id for item in first.failures] == [failed]
    assert first.completed == (succeeded,)
    assert second.failures == ()
    assert second.resumed == (succeeded,)
    assert provider.calls.count(str(succeeded)) == 1
    assert provider.calls.count(str(failed)) == 2


def test_checkpoint_cannot_be_reused_for_a_different_request(tmp_path: Path) -> None:
    collector = AkShareFiveMinuteBatchCollector(
        provider=FakeProvider(), checkpoint_path=tmp_path / "checkpoint"
    )
    collector.collect(
        instruments=(InstrumentId.parse("600000.SSE"),),
        trading_date=date(2026, 7, 24),
    )

    with pytest.raises(ValueError, match="different batch request"):
        collector.collect(
            instruments=(InstrumentId.parse("600000.SSE"),),
            trading_date=date(2026, 7, 25),
        )


def test_exploratory_batch_evidence_is_rejected_by_formal_gate(tmp_path: Path) -> None:
    result = AkShareFiveMinuteBatchCollector(
        provider=FakeProvider(), checkpoint_path=tmp_path / "checkpoint"
    ).collect(
        instruments=(InstrumentId.parse("600000.SSE"),),
        trading_date=date(2026, 7, 24),
    )

    EvidenceGate().admit(RunClass.EXPLORATORY, roots=(result.evidence,))
    with pytest.raises(FormalAdmissionError, match="EXPLORATORY_ONLY"):
        EvidenceGate().admit(RunClass.FORMAL, roots=(result.evidence,))
