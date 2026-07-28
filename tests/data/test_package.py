from importlib.util import find_spec


def test_data_package_and_native_engines_are_installed() -> None:
    assert find_spec("astraquant_data") is not None
    assert find_spec("duckdb") is not None
    assert find_spec("pyarrow") is not None
