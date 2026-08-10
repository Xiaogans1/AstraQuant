from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from astraquant_data.provider_identity import (
    ProviderCapability,
    ProviderIdentity,
    ProviderTransport,
)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _identity(**changes: object) -> ProviderIdentity:
    values: dict[str, object] = {
        "vendor": "eastmoney",
        "product": "eastmoney-terminal",
        "endpoint": "market.daily-bars",
        "capability": ProviderCapability.DAILY_BARS,
        "interface": "gm_python_sdk",
        "interface_build": "3.0.176",
        "transport": ProviderTransport.NDJSON_BRIDGE,
        "permission_tier": "level1-history",
        "schema_fingerprint": _digest("1"),
    }
    values.update(changes)
    return ProviderIdentity(**values)  # type: ignore[arg-type]


def test_eastmoney_provider_identity_separates_vendor_interface_and_transport() -> None:
    identity = _identity()

    assert identity.vendor == "eastmoney"
    assert identity.interface == "gm_python_sdk"
    assert identity.transport is ProviderTransport.NDJSON_BRIDGE
    assert identity.endpoint == "market.daily-bars"
    assert identity.capability is ProviderCapability.DAILY_BARS
    assert identity.identity_digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vendor", "Eastmoney/GM"),
        ("vendor", " eastmoney"),
        ("interface", "GM Python SDK"),
        ("permission_tier", ""),
        ("product", " eastmoney-terminal"),
        ("endpoint", ""),
        ("interface_build", "3.0.176 "),
        ("schema_fingerprint", "sha256:not-a-digest"),
        ("schema_fingerprint", f"sha256:{'0' * 64}"),
    ],
)
def test_provider_identity_rejects_noncanonical_or_incomplete_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        _identity(**{field: value})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda identity: replace(identity, endpoint="market.minute-bars"),
        lambda identity: replace(
            identity,
            capability=ProviderCapability.MINUTE_BARS,
        ),
        lambda identity: replace(identity, interface_build="3.0.177"),
        lambda identity: replace(identity, permission_tier="level2-history"),
        lambda identity: replace(identity, schema_fingerprint=_digest("2")),
    ],
)
def test_provider_identity_digest_changes_for_every_qualification_boundary(
    mutate: Callable[[ProviderIdentity], ProviderIdentity],
) -> None:
    identity = _identity()

    changed = mutate(identity)

    assert changed.identity_digest != identity.identity_digest


def test_same_vendor_capabilities_have_distinct_identities() -> None:
    identities = [
        _identity(
            endpoint=f"endpoint.{capability.value.casefold()}",
            capability=capability,
        )
        for capability in ProviderCapability
    ]

    assert {identity.capability for identity in identities} == {
        ProviderCapability.DAILY_BARS,
        ProviderCapability.MINUTE_BARS,
        ProviderCapability.CORPORATE_ACTIONS,
        ProviderCapability.INSTRUMENT_STATUS,
        ProviderCapability.L2_QUOTES,
    }
    assert len({identity.identity_digest for identity in identities}) == len(identities)
