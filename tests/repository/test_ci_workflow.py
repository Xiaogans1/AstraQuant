from pathlib import Path


def test_ruff_only_checks_python_source_and_tests() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "uv run ruff format --check packages tools tests" in workflow
    assert "uv run ruff check packages tools tests" in workflow
    assert "uv run ruff format --check ." not in workflow
    assert "uv run ruff check ." not in workflow
