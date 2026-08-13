from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.research.prepare_kronos_weights import (
    KRONOS_MODEL_REVISION,
    KRONOS_TOKENIZER_REVISION,
    prepare_artifact,
)


def test_rejects_unknown_or_unpinned_artifact_before_download(tmp_path: Path) -> None:
    called = False

    def downloader(**kwargs: object) -> Path:
        nonlocal called
        called = True
        return Path(str(kwargs["local_dir"]))

    with pytest.raises(ValueError, match="approved Kronos artifact"):
        prepare_artifact(
            repo_id="someone/other-model",
            revision=KRONOS_MODEL_REVISION,
            root=tmp_path,
            downloader=downloader,
        )
    with pytest.raises(ValueError, match="revision mismatch"):
        prepare_artifact(
            repo_id="NeoQuasar/Kronos-base",
            revision="main",
            root=tmp_path,
            downloader=downloader,
        )
    assert called is False


def test_downloads_exact_revision_and_seals_local_file_digests(tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    def downloader(**kwargs: object) -> Path:
        observed.update(kwargs)
        destination = Path(str(kwargs["local_dir"]))
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "config.json").write_bytes(b'{"model":"frozen"}\n')
        (destination / "model.safetensors").write_bytes(b"exact weights")
        return destination

    result = prepare_artifact(
        repo_id="NeoQuasar/Kronos-Tokenizer-base",
        revision=KRONOS_TOKENIZER_REVISION,
        root=tmp_path,
        downloader=downloader,
    )

    assert observed["repo_id"] == "NeoQuasar/Kronos-Tokenizer-base"
    assert observed["revision"] == KRONOS_TOKENIZER_REVISION
    assert observed["allow_patterns"] == ["config.json", "model.safetensors"]
    assert result.directory == (
        tmp_path
        / ".astraquant"
        / "models"
        / "kronos"
        / "Kronos-Tokenizer-base"
        / KRONOS_TOKENIZER_REVISION
    )
    assert result.weights_digest == (
        "sha256:" + hashlib.sha256(b"exact weights").hexdigest()
    )
    manifest = json.loads((result.directory / "artifact-manifest.json").read_text())
    assert manifest["repo_id"] == "NeoQuasar/Kronos-Tokenizer-base"
    assert manifest["revision"] == KRONOS_TOKENIZER_REVISION
    assert manifest["files"] == {
        "config.json": "sha256:"
        + hashlib.sha256(b'{"model":"frozen"}\n').hexdigest(),
        "model.safetensors": result.weights_digest,
    }


def test_existing_sealed_artifact_is_verified_without_redownload(tmp_path: Path) -> None:
    calls = 0

    def downloader(**kwargs: object) -> Path:
        nonlocal calls
        calls += 1
        destination = Path(str(kwargs["local_dir"]))
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "config.json").write_bytes(b"config")
        (destination / "model.safetensors").write_bytes(b"weights")
        return destination

    first = prepare_artifact(
        repo_id="NeoQuasar/Kronos-base",
        revision=KRONOS_MODEL_REVISION,
        root=tmp_path,
        downloader=downloader,
    )
    second = prepare_artifact(
        repo_id="NeoQuasar/Kronos-base",
        revision=KRONOS_MODEL_REVISION,
        root=tmp_path,
        downloader=downloader,
    )
    assert first == second
    assert calls == 1

    (first.directory / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="local artifact digest mismatch"):
        prepare_artifact(
            repo_id="NeoQuasar/Kronos-base",
            revision=KRONOS_MODEL_REVISION,
            root=tmp_path,
            downloader=downloader,
        )
    assert calls == 1
