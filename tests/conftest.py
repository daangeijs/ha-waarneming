"""Shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

FIXTURES = Path(__file__).parent / "fixtures"
API = "https://waarneming.nl/api/v1"
AROUND_URL = f"{API}/observations/around-point/"
AREA_URL = f"{API}/locations/701925/observations/"
GEOJSON_URL = f"{API}/locations/geojson/"

# A made-up home point in the example area (Flevoland), nowhere near anyone's house.
HOME = (52.40, 5.30)


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load custom_components/waarneming."""


@pytest.fixture
def home_zone(hass: HomeAssistant) -> tuple[float, float]:
    hass.states.async_set("zone.home", "0", {"latitude": HOME[0], "longitude": HOME[1]})
    return HOME
