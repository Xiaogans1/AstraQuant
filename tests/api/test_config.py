from pathlib import Path

import pytest

from astraquant_api.config import RuntimeConfig, validate_runtime_root_layout


def test_load_config_requires_token_and_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASTRAQUANT_SESSION_TOKEN", "x" * 43)
    monkeypatch.setenv("ASTRAQUANT_STATE_DIR", str(tmp_path))

    config = RuntimeConfig.from_environment()

    assert config.host == "127.0.0.1"
    assert config.port == 0
    assert config.database_path.parent == tmp_path / "state"
    assert config.log_dir == tmp_path / "logs"
    assert config.legacy_data_root == tmp_path / "data"
    assert config.formal_qualification_root == tmp_path / "formal" / "qualification"
    assert config.formal_capture_root == tmp_path / "formal" / "capture"
    assert config.formal_publication_root == tmp_path / "formal" / "publication"
    assert config.formal_verification_root == tmp_path / "formal" / "verification"
    assert not (tmp_path / "qualification").exists()
    leaf_roots = (
        config.legacy_data_root,
        config.formal_qualification_root,
        config.formal_capture_root,
        config.formal_publication_root,
        config.formal_verification_root,
    )
    assert all(path.is_dir() and path == path.resolve() for path in leaf_roots)
    assert all(
        first not in second.parents and second not in first.parents
        for index, first in enumerate(leaf_roots)
        for second in leaf_roots[index + 1 :]
    )


def test_reject_short_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASTRAQUANT_SESSION_TOKEN", "short")
    monkeypatch.setenv("ASTRAQUANT_STATE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="session token"):
        RuntimeConfig.from_environment()


def test_runtime_root_layout_rejects_escape_and_overlap(tmp_path: Path) -> None:
    state_dir = tmp_path / "state-dir"
    outside = tmp_path / "outside"

    with pytest.raises(ValueError, match="escapes state directory"):
        validate_runtime_root_layout(
            state_dir,
            {
                "legacy_data": state_dir / "data",
                "formal_capture": outside / "capture",
            },
        )
    with pytest.raises(ValueError, match="overlap"):
        validate_runtime_root_layout(
            state_dir,
            {
                "legacy_data": state_dir / "data",
                "formal_capture": state_dir / "data" / "capture",
            },
        )


def test_runtime_root_layout_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    state_dir = tmp_path / "state-dir"
    formal_root = state_dir / "formal"
    outside = tmp_path / "outside"
    formal_root.mkdir(parents=True)
    outside.mkdir()
    link = formal_root / "capture"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this Windows account")

    with pytest.raises(ValueError, match="escapes state directory"):
        validate_runtime_root_layout(
            state_dir,
            {
                "legacy_data": state_dir / "data",
                "formal_capture": link,
            },
        )
