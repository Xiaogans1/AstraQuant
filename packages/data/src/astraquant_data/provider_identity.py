"""Immutable identity for one qualified provider endpoint and capability."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from astraquant_domain.run_manifest import canonical_json_bytes, validate_digest

_SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")


class ProviderCapability(StrEnum):
    DAILY_BARS = "DAILY_BARS"
    MINUTE_BARS = "MINUTE_BARS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    INSTRUMENT_STATUS = "INSTRUMENT_STATUS"
    L2_QUOTES = "L2_QUOTES"


class ProviderTransport(StrEnum):
    NDJSON_BRIDGE = "NDJSON_BRIDGE"
    DIRECT_SDK = "DIRECT_SDK"
    HTTP = "HTTP"


def _validate_slug(name: str, value: str) -> str:
    if not isinstance(value, str) or _SLUG_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical lowercase slug")
    return value


def _validate_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    vendor: str
    product: str
    endpoint: str
    capability: ProviderCapability
    interface: str
    interface_build: str
    transport: ProviderTransport
    permission_tier: str
    schema_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "vendor", _validate_slug("vendor", self.vendor))
        object.__setattr__(self, "product", _validate_text("product", self.product))
        object.__setattr__(self, "endpoint", _validate_text("endpoint", self.endpoint))
        if not isinstance(self.capability, ProviderCapability):
            raise ValueError("capability must be a known ProviderCapability")
        object.__setattr__(self, "interface", _validate_slug("interface", self.interface))
        object.__setattr__(
            self,
            "interface_build",
            _validate_text("interface_build", self.interface_build),
        )
        if not isinstance(self.transport, ProviderTransport):
            raise ValueError("transport must be a known ProviderTransport")
        object.__setattr__(
            self,
            "permission_tier",
            _validate_slug("permission_tier", self.permission_tier),
        )
        object.__setattr__(
            self,
            "schema_fingerprint",
            validate_digest("schema_fingerprint", self.schema_fingerprint),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "vendor": self.vendor,
            "product": self.product,
            "endpoint": self.endpoint,
            "capability": self.capability.value,
            "interface": self.interface,
            "interface_build": self.interface_build,
            "transport": self.transport.value,
            "permission_tier": self.permission_tier,
            "schema_fingerprint": self.schema_fingerprint,
        }

    @property
    def identity_digest(self) -> str:
        digest = hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()
        return f"sha256:{digest}"
