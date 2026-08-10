from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest


def test_symbol_search_loads_tradeable_asset_types_and_filters_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_instrumentinfos = Mock(
        side_effect=[
            [
                {"symbol": "SHSE.600000", "sec_name": "浦发银行"},
                {"symbol": "SZSE.000001", "sec_name": "平安银行"},
                {"symbol": "SHSE.510300", "sec_name": "沪深300ETF"},
            ],
            [{"symbol": "SHFE.rb2610", "sec_name": "螺纹钢2610"}],
        ]
    )
    fake_api = SimpleNamespace(
        SEC_TYPE_STOCK=1,
        SEC_TYPE_FUND=2,
        SEC_TYPE_FUTURE=4,
        ADJUST_NONE=0,
        ADJUST_PREV=1,
        ADJUST_POST=2,
        get_instrumentinfos=get_instrumentinfos,
    )
    fake_gm = ModuleType("gm")
    fake_gm.api = fake_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gm", fake_gm)
    sys.modules.pop("tools.eastmoney_bridge", None)
    bridge = importlib.import_module("tools.eastmoney_bridge")

    result = bridge.invoke("search_symbols", {"query": "浦发"})

    assert result == [{"symbol": "SHSE.600000", "sec_name": "浦发银行"}]
    assert get_instrumentinfos.call_args_list == [
        call(sec_types=[1, 2], exchanges=["SHSE", "SZSE", "BSE"], df=False),
        call(
            sec_types=[4],
            exchanges=["CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"],
            df=False,
        ),
    ]


def test_history_range_uses_explicit_boundaries_and_reports_unproven_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = Mock(
        return_value=[
            {
                "symbol": "SHSE.600000",
                "bob": "2026-08-01T00:00:00+00:00",
            }
        ]
    )
    fake_api = SimpleNamespace(
        ADJUST_NONE=0,
        ADJUST_PREV=1,
        ADJUST_POST=2,
        history=history,
    )
    fake_gm = ModuleType("gm")
    fake_gm.api = fake_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gm", fake_gm)
    sys.modules.pop("tools.eastmoney_bridge", None)
    bridge = importlib.import_module("tools.eastmoney_bridge")

    result = bridge.invoke(
        "history_range",
        {
            "symbol": "SHSE.600000",
            "frequency": "1d",
            "adjust": 0,
            "units": ["price=CNY", "volume=share"],
            "page": {
                "index": 0,
                "page_count": 1,
                "cursor": "page-0",
                "start_at": "2026-08-01T00:00:00+00:00",
                "end_at": "2026-08-02T00:00:00+00:00",
            },
        },
    )

    history.assert_called_once_with(
        symbol="SHSE.600000",
        frequency="1d",
        start_time="2026-08-01T00:00:00+00:00",
        end_time="2026-08-02T00:00:00+00:00",
        adjust=0,
        df=True,
    )
    assert result["page"]["returned_count"] == 1
    assert result["page"]["declared_total"] is None
