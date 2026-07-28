from tools.repository_policy import MAX_FIXTURE_CSV_BYTES, find_forbidden_paths


def test_allow_source_and_small_fixture_files() -> None:
    paths = [
        "packages/data/pyproject.toml",
        "packages/data/src/astraquant_data/providers.py",
        "tests/data/test_providers.py",
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
