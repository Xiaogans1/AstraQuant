from tools.repository_policy import find_forbidden_paths


def test_allow_source_and_small_fixture_files() -> None:
    paths = [
        "packages/domain/src/astraquant_domain/orders.py",
        "tests/fixtures/orders/sample_order.json",
        ".env.example",
    ]

    assert find_forbidden_paths(paths) == []


def test_reject_private_data_and_runtime_files() -> None:
    paths = [
        ".env",
        "data/sse/2026-07-27.parquet",
        "runtime/astraquant.sqlite3",
        "models/alpha.ckpt",
        "credentials-prod.json",
    ]

    assert find_forbidden_paths(paths) == paths
