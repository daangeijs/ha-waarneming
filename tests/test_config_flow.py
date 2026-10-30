"""Config and options flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waarneming.const import DOMAIN

from .conftest import API, AREA_URL, load

BASE_INPUT = {
    "name": "Rare birds nearby",
    "use_home": True,
    "radius_km": 10,
    "min_rarity": "3",
    "days": 3,
    "species_group": 1,
    "max_sightings": 10,
}
OVP = {"id": 701925, "name": "Oostvaardersplassen - N2000"}


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.waarneming.async_setup_entry", return_value=True):
        yield


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_home_only(hass: HomeAssistant) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], BASE_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Rare birds nearby"
    assert result["data"] == {}
    assert result["options"] == {
        "use_home": True,
        "radius_km": 10,
        "min_rarity": 3,
        "days": 3,
        "species_group": 1,
        "max_sightings": 10,
        "areas": [],
    }


@pytest.mark.parametrize(
    "text",
    [
        "701925",
        "https://waarneming.nl/locations/701925/",
        "  https://waarneming.nl/locations/701925/observations/ \n",
    ],
)
async def test_area_by_id_or_url(
    hass: HomeAssistant, aioclient_mock, text: str
) -> None:
    aioclient_mock.get(AREA_URL, json=load("area_name_self.json"))
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_INPUT, "use_home": False, "add_areas": text}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert (
        "Oostvaardersplassen - N2000 (701925)"
        in result["description_placeholders"]["regions"]
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["areas"] == [OVP]
    assert result["options"]["use_home"] is False


async def test_invalid_area_text(hass: HomeAssistant) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**BASE_INPUT, "add_areas": "https://waarneming.nl/species/52/"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"add_areas": "invalid_area"}


async def test_unknown_area(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/locations/999999999/observations/", status=404)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_INPUT, "add_areas": "999999999"}
    )
    assert result["errors"] == {"add_areas": "area_not_found"}
    assert result["description_placeholders"]["area"] == "999999999"


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(AREA_URL, status=500)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_INPUT, "add_areas": "701925"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_no_source(hass: HomeAssistant) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_INPUT, "use_home": False}
    )
    assert result["errors"] == {"base": "no_source"}


def _entry(hass: HomeAssistant, areas: list) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rare birds nearby",
        data={},
        options={
            "use_home": True,
            "radius_km": 10,
            "areas": areas,
            "min_rarity": 3,
            "days": 3,
            "species_group": 1,
            "max_sightings": 10,
            "scan_minutes": 30,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_add_area(hass: HomeAssistant, aioclient_mock) -> None:
    entry = _entry(hass, [])
    aioclient_mock.get(AREA_URL, json=load("area_name_self.json"))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    opts = {k: v for k, v in BASE_INPUT.items() if k != "name"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **opts,
            "scan_minutes": 45,
            "add_areas": "https://waarneming.nl/locations/701925/",
        },
    )
    assert result["step_id"] == "confirm"
    assert (
        "Oostvaardersplassen - N2000" in result["description_placeholders"]["regions"]
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["areas"] == [OVP]
    assert entry.options["scan_minutes"] == 45


async def test_options_remove_area_keeps_cached_names(
    hass: HomeAssistant, aioclient_mock
) -> None:
    other = {"id": 800201, "name": "Oostvaardersplassen - Kijkhut"}
    entry = _entry(hass, [OVP, other])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert (
        "Oostvaardersplassen - Kijkhut (800201)"
        in result["description_placeholders"]["regions"]
    )
    opts = {k: v for k, v in BASE_INPUT.items() if k != "name"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**opts, "scan_minutes": 30, "areas": ["800201"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["areas"] == [other]
    assert aioclient_mock.call_count == 0  # no lookups for areas we already know


async def test_options_scan_interval_floor(hass: HomeAssistant) -> None:
    entry = _entry(hass, [])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    opts = {k: v for k, v in BASE_INPUT.items() if k != "name"}
    with pytest.raises(InvalidData):  # the selector refuses < 15 minutes
        await hass.config_entries.options.async_configure(
            result["flow_id"], {**opts, "scan_minutes": 5}
        )
