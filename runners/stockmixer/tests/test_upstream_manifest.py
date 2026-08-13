from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_upstream_manifest_matches_pinned_checkout() -> None:
    root = Path(__file__).parents[3]
    manifest = json.loads(
        (root / "runners/stockmixer/upstream-manifest.json").read_text(encoding="utf-8")
    )
    upstream = root / "external/StockMixer"

    assert manifest["contract"] == "astraquant.stockmixer-upstream/v1"
    assert manifest["repository"] == "https://github.com/SJTU-DMTai/StockMixer.git"
    assert manifest["commit"] == "cce13598afd3ff33ae317700a85ae08db0554652"
    assert _sha256(upstream / "src/model.py") == manifest["evidence"]["model_sha256"]
    assert _sha256(upstream / "src/train.py") == manifest["evidence"]["train_sha256"]
    assert (
        _sha256(upstream / "paper+slide+poster/StockMixer.pdf")
        == manifest["evidence"]["paper_sha256"]
    )
    assert manifest["integration_policy"] == {
        "dynamic_universe_required": True,
        "main_process_imports_torch": False,
        "sample_datasets_allowed": False,
        "upstream_source_read_only": True,
    }
