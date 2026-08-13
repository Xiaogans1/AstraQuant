"""Prepare exact, locally sealed Kronos weights outside the inference process."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KRONOS_MODEL_ID = "NeoQuasar/Kronos-base"
KRONOS_MODEL_REVISION = "2b554741eca47781b64468546e77fef3e85130e6"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
KRONOS_TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"

_APPROVED = {
    KRONOS_MODEL_ID: KRONOS_MODEL_REVISION,
    KRONOS_TOKENIZER_ID: KRONOS_TOKENIZER_REVISION,
}
_REQUIRED_FILES = ("config.json", "model.safetensors")

Downloader = Callable[..., str | Path]


@dataclass(frozen=True)
class PreparedArtifact:
    directory: Path
    weights_digest: str


def prepare_artifact(
    *, repo_id: str, revision: str, root: Path, downloader: Downloader
) -> PreparedArtifact:
    expected = _APPROVED.get(repo_id)
    if expected is None:
        raise ValueError("repository is not an approved Kronos artifact")
    if revision != expected:
        raise ValueError("Kronos artifact revision mismatch")
    destination = (
        root.resolve()
        / ".astraquant"
        / "models"
        / "kronos"
        / repo_id.rsplit("/", 1)[-1]
        / revision
    )
    if destination.exists():
        return _verify_existing(destination, repo_id=repo_id, revision=revision)

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        downloaded = Path(
            downloader(
                repo_id=repo_id,
                revision=revision,
                local_dir=staging,
                allow_patterns=list(_REQUIRED_FILES),
            )
        ).resolve()
        if downloaded != staging.resolve():
            raise ValueError("Kronos downloader escaped the staging directory")
        files = _required_digests(staging)
        manifest = {
            "schema_version": "astraquant.kronos-local-artifact/v1",
            "repo_id": repo_id,
            "revision": revision,
            "files": files,
        }
        (staging / "artifact-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        staging.replace(destination)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return PreparedArtifact(
        directory=destination,
        weights_digest=files["model.safetensors"],
    )


def prepare_frozen_weights(*, root: Path, downloader: Downloader) -> dict[str, object]:
    model = prepare_artifact(
        repo_id=KRONOS_MODEL_ID,
        revision=KRONOS_MODEL_REVISION,
        root=root,
        downloader=downloader,
    )
    tokenizer = prepare_artifact(
        repo_id=KRONOS_TOKENIZER_ID,
        revision=KRONOS_TOKENIZER_REVISION,
        root=root,
        downloader=downloader,
    )
    return {
        "model": _result(model, root),
        "tokenizer": _result(tokenizer, root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare pinned Kronos weights")
    parser.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

    result = prepare_frozen_weights(root=arguments.root, downloader=snapshot_download)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _verify_existing(
    directory: Path, *, repo_id: str, revision: str
) -> PreparedArtifact:
    manifest_path = directory / "artifact-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("existing local artifact is not sealed")
    value: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("local artifact manifest is invalid")
    expected_files = _required_digests(directory)
    if value != {
        "schema_version": "astraquant.kronos-local-artifact/v1",
        "repo_id": repo_id,
        "revision": revision,
        "files": expected_files,
    }:
        raise ValueError("local artifact digest mismatch")
    return PreparedArtifact(
        directory=directory,
        weights_digest=expected_files["model.safetensors"],
    )


def _required_digests(directory: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for name in _REQUIRED_FILES:
        path = directory / name
        if not path.is_file():
            raise ValueError(f"Kronos artifact is missing {name}")
        digests[name] = _digest(path)
    return digests


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _result(artifact: PreparedArtifact, root: Path) -> dict[str, str]:
    return {
        "directory": artifact.directory.relative_to(root.resolve()).as_posix(),
        "weights_digest": artifact.weights_digest,
    }


if __name__ == "__main__":
    raise SystemExit(main())
