from importlib.resources import files
from importlib.util import find_spec


def test_data_package_and_native_engines_are_installed() -> None:
    assert find_spec("astraquant_data") is not None
    assert find_spec("duckdb") is not None
    assert find_spec("pyarrow") is not None


def test_domain_package_publishes_its_type_information() -> None:
    assert files("astraquant_domain").joinpath("py.typed").is_file()
