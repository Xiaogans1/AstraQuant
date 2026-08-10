"""Immutable identity contract for reproducible AstraQuant runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Self

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ZERO_DIGEST = "sha256:" + "0" * 64


class RunClass(StrEnum):
    FORMAL = "FORMAL"
    EXPLORATORY = "EXPLORATORY"
    TEST = "TEST"


class RunManifestState(StrEnum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"


class UnsealedRunManifestError(RuntimeError):
    """Raised when a draft manifest is used to start or identify a run."""


def validate_digest(name: str, value: str) -> str:
    """Return a canonical SHA-256 digest or fail closed."""

    if not _DIGEST_PATTERN.fullmatch(value) or value == _ZERO_DIGEST:
        raise ValueError(f"{name} must be a non-sentinel sha256 digest")
    return value


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON-compatible identity data deterministically."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _freeze_digest_mapping(name: str, values: Mapping[str, str]) -> Mapping[str, str]:
    if not values:
        raise ValueError(f"{name} must not be empty")
    frozen: dict[str, str] = {}
    for key, digest in sorted(values.items()):
        if not key or key != key.strip():
            raise ValueError(f"{name} keys must be non-empty canonical names")
        frozen[key] = validate_digest(f"{name}[{key}]", digest)
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Complete immutable identity for one reproducible run."""

    run_class: RunClass
    code_digest: str
    environment_digest: str
    input_digests: Mapping[str, str]
    config_digest: str
    randomness_digest: str
    event_order_policy_digest: str
    matcher_policy_digest: str
    vintage_policy_digest: str
    policy_digests: Mapping[str, str]
    state: RunManifestState = RunManifestState.DRAFT
    schema_version: str = "astraquant.run-manifest/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.run_class, RunClass):
            raise ValueError("run_class must be a known RunClass")
        if not isinstance(self.state, RunManifestState):
            raise ValueError("state must be a known RunManifestState")
        if self.schema_version != "astraquant.run-manifest/v1":
            raise ValueError("unknown run manifest schema_version")
        for name in (
            "code_digest",
            "environment_digest",
            "config_digest",
            "randomness_digest",
            "event_order_policy_digest",
            "matcher_policy_digest",
            "vintage_policy_digest",
        ):
            object.__setattr__(self, name, validate_digest(name, getattr(self, name)))
        object.__setattr__(
            self,
            "input_digests",
            _freeze_digest_mapping("input_digests", self.input_digests),
        )
        object.__setattr__(
            self,
            "policy_digests",
            _freeze_digest_mapping("policy_digests", self.policy_digests),
        )

    def seal(self) -> Self:
        if self.state is RunManifestState.SEALED:
            return self
        return replace(self, state=RunManifestState.SEALED)

    def assert_runnable(self) -> None:
        if self.state is not RunManifestState.SEALED:
            raise UnsealedRunManifestError("run manifest must be SEALED before execution")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "run_class": self.run_class.value,
            "code_digest": self.code_digest,
            "environment_digest": self.environment_digest,
            "input_digests": dict(self.input_digests),
            "config_digest": self.config_digest,
            "randomness_digest": self.randomness_digest,
            "event_order_policy_digest": self.event_order_policy_digest,
            "matcher_policy_digest": self.matcher_policy_digest,
            "vintage_policy_digest": self.vintage_policy_digest,
            "policy_digests": dict(self.policy_digests),
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def manifest_digest(self) -> str:
        self.assert_runnable()
        return f"sha256:{hashlib.sha256(self.to_canonical_bytes()).hexdigest()}"
