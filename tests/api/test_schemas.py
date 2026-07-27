import pytest
from pydantic import ValidationError

from astraquant_api.schemas import Settings


@pytest.mark.parametrize("theme", ["astra-minimal", "astra-light"])
def test_accept_supported_themes(theme: str) -> None:
    settings = Settings.model_validate({"theme": theme})
    assert settings.theme == theme


@pytest.mark.parametrize("theme", ["unknown", "nebula-boy", ""])
def test_reject_unsupported_themes(theme: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"theme": theme})


@pytest.mark.parametrize("effect", ["none", "nebula", "grid"])
def test_accept_supported_background_effects(effect: str) -> None:
    settings = Settings.model_validate({"background_effect": effect})
    assert settings.background_effect == effect


def test_reject_unknown_setting_fields() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"theme": "astra-minimal", "unknown": True})
