from __future__ import annotations

from pathlib import Path

import pytest
import torch
from astraquant_stockmixer_runner.artifacts import (
    load_model_state,
    write_training_artifact,
)
from astraquant_stockmixer_runner.training import train_fold

from .test_training import _config, _request


def test_artifact_is_byte_repeatable_and_loadable(tmp_path: Path) -> None:
    request = _request()
    config = _config()
    first_result = train_fold(request, fold_id="fold-0", config=config)
    second_result = train_fold(request, fold_id="fold-0", config=config)

    first = write_training_artifact(
        first_result,
        request=request,
        config=config,
        output_root=tmp_path / "first",
    )
    second = write_training_artifact(
        second_result,
        request=request,
        config=config,
        output_root=tmp_path / "second",
    )

    assert first.content_digest == second.content_digest
    assert first.response_path.read_bytes() == second.response_path.read_bytes()
    assert first.model_path.read_bytes() == second.model_path.read_bytes()
    assert first.predictions_path.read_bytes() == second.predictions_path.read_bytes()
    loaded = load_model_state(first.model_path)
    for name, expected in first_result.model.state_dict().items():
        torch.testing.assert_close(loaded[name], expected.cpu(), rtol=0, atol=0)


def test_artifact_refuses_overwrite(tmp_path: Path) -> None:
    request = _request()
    config = _config()
    result = train_fold(request, fold_id="fold-0", config=config)
    output = tmp_path / "sealed"
    write_training_artifact(result, request=request, config=config, output_root=output)

    with pytest.raises(ValueError, match="must not already exist"):
        write_training_artifact(result, request=request, config=config, output_root=output)

