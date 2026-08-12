from astraquant_api.cli import _resolve_market_provider_id


def test_auto_provider_stays_off_without_sdk() -> None:
    assert _resolve_market_provider_id("auto", sdk_configured=False, platform="darwin") == "none"
    assert _resolve_market_provider_id("auto", sdk_configured=False, platform="win32") == "none"
    assert _resolve_market_provider_id("auto", sdk_configured=False, platform="linux") == "none"


def test_auto_provider_prefers_configured_eastmoney_sdk() -> None:
    assert (
        _resolve_market_provider_id("auto", sdk_configured=True, platform="darwin") == "eastmoney"
    )


def test_explicit_provider_overrides_platform_default() -> None:
    assert (
        _resolve_market_provider_id("akshare", sdk_configured=False, platform="win32") == "akshare"
    )
    assert _resolve_market_provider_id("none", sdk_configured=True, platform="darwin") == "none"
