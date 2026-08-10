from dataclasses import FrozenInstanceError

import pytest

from astraquant_domain.run_manifest import (
    RunClass,
    RunManifest,
    RunManifestState,
    UnsealedRunManifestError,
)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _draft(**overrides: object) -> RunManifest:
    values: dict[str, object] = {
        "run_class": RunClass.FORMAL,
        "code_digest": _digest("1"),
        "environment_digest": _digest("2"),
        "input_digests": {"bars": _digest("3"), "rules": _digest("4")},
        "config_digest": _digest("5"),
        "randomness_digest": _digest("6"),
        "event_order_policy_digest": _digest("7"),
        "matcher_policy_digest": _digest("8"),
        "vintage_policy_digest": _digest("9"),
        "policy_digests": {"risk": _digest("a"), "fees": _digest("b")},
    }
    values.update(overrides)
    return RunManifest(**values)  # type: ignore[arg-type]


def test_sealed_manifest_is_canonical_and_runnable() -> None:
    first = _draft(
        input_digests={"bars": _digest("3"), "rules": _digest("4")},
        policy_digests={"risk": _digest("a"), "fees": _digest("b")},
    ).seal()
    second = _draft(
        input_digests={"rules": _digest("4"), "bars": _digest("3")},
        policy_digests={"fees": _digest("b"), "risk": _digest("a")},
    ).seal()

    assert first.state is RunManifestState.SEALED
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert first.manifest_digest == second.manifest_digest
    assert first.seal() is first
    first.assert_runnable()


def test_draft_manifest_cannot_start_a_run() -> None:
    with pytest.raises(UnsealedRunManifestError, match="SEALED"):
        _draft().assert_runnable()


def test_sealed_manifest_and_nested_mappings_are_immutable() -> None:
    inputs = {"bars": _digest("3")}
    sealed = _draft(input_digests=inputs).seal()
    inputs["bars"] = _digest("c")

    assert sealed.input_digests["bars"] == _digest("3")
    with pytest.raises(FrozenInstanceError):
        sealed.run_class = RunClass.TEST  # type: ignore[misc]
    with pytest.raises(TypeError):
        sealed.input_digests["bars"] = _digest("c")  # type: ignore[index]


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_class": RunClass.EXPLORATORY},
        {"code_digest": _digest("c")},
        {"environment_digest": _digest("c")},
        {"input_digests": {"bars": _digest("c")}},
        {"config_digest": _digest("c")},
        {"randomness_digest": _digest("c")},
        {"event_order_policy_digest": _digest("c")},
        {"matcher_policy_digest": _digest("c")},
        {"vintage_policy_digest": _digest("c")},
        {"policy_digests": {"risk": _digest("c")}},
    ],
)
def test_every_identity_field_changes_the_sealed_digest(
    overrides: dict[str, object],
) -> None:
    assert _draft().seal().manifest_digest != _draft(**overrides).seal().manifest_digest


@pytest.mark.parametrize(
    "bad_digest",
    [
        "",
        "abc123",
        "sha256:ABCDEF" + "0" * 58,
        "sha256:" + "0" * 64,
        "sha512:" + "1" * 64,
    ],
)
def test_manifest_rejects_invalid_or_sentinel_digests(bad_digest: str) -> None:
    with pytest.raises(ValueError, match="digest"):
        _draft(code_digest=bad_digest)


@pytest.mark.parametrize("field", ["input_digests", "policy_digests"])
def test_manifest_requires_named_digest_collections(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _draft(**{field: {}})


def test_manifest_digest_is_unavailable_until_sealed() -> None:
    with pytest.raises(UnsealedRunManifestError, match="SEALED"):
        _ = _draft().manifest_digest
