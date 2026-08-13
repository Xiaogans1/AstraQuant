from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from astraquant_stockmixer_runner import __main__ as cli


def test_train_command_passes_sealed_configuration(monkeypatch, tmp_path: Path) -> None:
    request = object()
    result = SimpleNamespace(fold_id="fold-7")
    calls: dict[str, object] = {}
    monkeypatch.setattr(cli, "load_request", lambda path: request)

    def fake_train(loaded, *, fold_id, config, device):
        calls.update(loaded=loaded, fold_id=fold_id, config=config, device=device)
        return result

    def fake_write(trained, *, request, config, output_root):
        calls.update(trained=trained, output_root=output_root)
        return SimpleNamespace(response_path=output_root / "response.json")

    monkeypatch.setattr(cli, "train_fold", fake_train)
    monkeypatch.setattr(cli, "write_training_artifact", fake_write)

    exit_code = cli.main(
        [
            "train",
            "request.json",
            "--output-root",
            str(tmp_path / "run"),
            "--fold-id",
            "fold-7",
            "--device",
            "cpu",
            "--epochs",
            "3",
            "--scales",
            "1,2",
        ]
    )

    assert exit_code == 0
    assert calls["loaded"] is request
    assert calls["fold_id"] == "fold-7"
    assert calls["device"] == "cpu"
    assert calls["config"].epochs == 3
    assert calls["config"].scales == (1, 2)
    assert calls["output_root"] == tmp_path / "run" / "fold-7"

