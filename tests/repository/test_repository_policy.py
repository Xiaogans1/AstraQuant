from pathlib import Path

from tools.repository_policy import (
    MAX_FIXTURE_CSV_BYTES,
    find_forbidden_content,
    find_forbidden_paths,
)


def test_quant_core_learning_guide_is_frozen_as_legacy_demo_evidence() -> None:
    guide = Path("docs/research/quant-core-learning-guide.md").read_text(encoding="utf-8")

    assert "LEGACY_SEMANTICS" in guide
    assert "demo" in guide.casefold()
    assert "不得作为 v3 alpha" in guide
    assert "../superpowers/specs/2026-08-10-quant-core-open-source-architecture-design.md" in guide
    assert "当前唯一生产模型" not in guide


def test_allow_source_and_small_fixture_files() -> None:
    paths = [
        "packages/data/pyproject.toml",
        "packages/data/src/astraquant_data/providers.py",
        "tests/data/test_providers.py",
        "tools/data/qualify_eastmoney.py",
        "tests/fixtures/market_data/cn_equity_daily_bars.csv",
        "packages/domain/src/astraquant_domain/orders.py",
        "tests/fixtures/orders/sample_order.json",
        ".env.example",
    ]

    assert (
        find_forbidden_paths(
            paths,
            file_sizes={
                "tests/fixtures/market_data/cn_equity_daily_bars.csv": 1_024,
            },
        )
        == []
    )


def test_reject_private_data_and_runtime_files() -> None:
    paths = [
        ".env",
        "data/sse/2026-07-27.parquet",
        "packages/data/src/astraquant_data/bundled_snapshot.parquet",
        "tests/fixtures/market_data/bundled_snapshot.duckdb",
        "runtime/astraquant.sqlite3",
        "runtime/astraquant.sqlite-wal",
        "downloads/history.csv",
        "models/alpha.safetensors",
        "models/alpha.ckpt",
        "credentials-prod.json",
    ]

    assert find_forbidden_paths(paths) == paths


def test_reject_oversized_market_data_fixture() -> None:
    fixture = "tests/fixtures/market_data/too-large.csv"

    assert find_forbidden_paths(
        [fixture],
        file_sizes={fixture: MAX_FIXTURE_CSV_BYTES + 1},
    ) == [fixture]


def test_reject_eastmoney_secrets_and_raw_market_dumps() -> None:
    paths = [
        "eastmoney-token.txt",
        "eastmoney-quotes.json",
        "eastmoney-ticks.jsonl",
        "gm-current-dump.json",
        ".astraquant/market/cache.json",
        "data/eastmoney/quotes.json",
    ]

    assert find_forbidden_paths(paths) == paths


def test_allow_sanitized_eastmoney_source_and_acceptance_docs() -> None:
    paths = [
        "tools/eastmoney_probe.py",
        "docs/research/eastmoney-realtime-acceptance.md",
        "tests/fixtures/eastmoney/sanitized-current.json",
    ]

    assert find_forbidden_paths(paths) == []


def test_reject_eastmoney_token_assignments_in_tracked_content() -> None:
    contents = {
        "notes/debug.txt": "ASTRAQUANT_EASTMONEY_TOKEN=secret-value-123",
        "tmp/config.json": '{"access_token": "secret-value-456"}',
        "tmp/another.json": '{"api_token": "secret-value-789"}',
    }

    assert find_forbidden_content(contents) == list(contents)


def test_reject_raw_captures_qualification_bodies_and_append_only_databases() -> None:
    paths = [
        "packages/data/raw-captures/eastmoney/page-1.json",
        "raw-captures/eastmoney/page-1.ndjson",
        "captures/eastmoney/daily.capture.json",
        "qualification-reports/eastmoney/report.json",
        "state/formal/catalog.sqlite-wal",
        "artifacts/verification/run.json",
        "models/champion.onnx",
    ]

    assert find_forbidden_paths(paths) == paths


def test_reject_generic_astraquant_tokens_and_secret_json_fields() -> None:
    contents = {
        "notes/token.txt": "ASTRAQUANT_BROKER_TOKEN=real-token",
        "tmp/config.json": '{"client_secret": "real-secret"}',
        "tmp/password.json": '{"password": "real-password"}',
    }

    assert find_forbidden_content(contents) == list(contents)


def test_allow_secret_field_names_in_source_and_env_template() -> None:
    contents = {
        ".env.example": "ASTRAQUANT_EASTMONEY_TOKEN=",
        "packages/api/src/schema.py": 'token: SecretStr = Field(description="token")',
        "tests/test_schema.py": '{"token": "[REDACTED]"}',
    }

    assert find_forbidden_content(contents) == []
