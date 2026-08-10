from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from astraquant_api.config import RuntimeConfig
from astraquant_api.database import create_database
from astraquant_api.paper_repository import PaperRepository
from tools.research import publish_model


def _configure_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    database_path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(
        RuntimeConfig,
        "from_environment",
        lambda: SimpleNamespace(database_path=database_path),
    )
    return database_path


def test_publish_model_rejects_formal_even_with_strong_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.txt"
    artifact.write_text("legacy model", encoding="utf-8")
    _configure_state(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="EXPLORATORY"):
        publish_model.register_approved_model(
            model_id="legacy-model",
            strategy_id="demo",
            strategy_version="v1",
            feature_version="v1",
            artifact_path=str(artifact),
            metrics={"auc": 0.99, "net_return": 9.0},
            force=True,
            run_class="FORMAL",
        )


def test_force_only_overwrites_explicit_legacy_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.txt"
    artifact.write_text("legacy model", encoding="utf-8")
    database_path = _configure_state(monkeypatch, tmp_path)
    for force in (False, True):
        publish_model.register_approved_model(
            model_id="legacy-model",
            strategy_id="demo",
            strategy_version="v1",
            feature_version="v1",
            artifact_path=str(artifact),
            metrics={"auc": 0.99, "net_return": 9.0},
            force=force,
        )

    record = PaperRepository(create_database(f"sqlite:///{database_path}")).get_model(
        "legacy-model"
    )
    assert record is not None
    assert record.status == "APPROVED"
    assert record.semantic_class == "LEGACY_SEMANTICS"
    assert record.evidence_class == "LEGACY_UNVERIFIED"
    assert record.run_class == "EXPLORATORY"
