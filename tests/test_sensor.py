"""The entity has the recipe's shape."""

from __future__ import annotations

import time

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waarneming.const import DOMAIN

from .conftest import AREA_URL, AROUND_URL, load

SIGHTING_KEYS = {
    "species",
    "scientific",
    "count",
    "place",
    "distance_km",
    "observed_at",
    "rarity",
    "certain",
    "region",
    "url",
    "title",
    "subtitle",
    "ts",
}


async def _setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Rare birds nearby",
        data={},
        options={
            "use_home": True,
            "radius_km": 10,
            "areas": [{"id": 701925, "name": "Oostvaardersplassen - N2000"}],
            "min_rarity": 3,
            "days": 3,
            "species_group": 1,
            "max_sightings": 10,
            **options,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entity_shape(hass: HomeAssistant, aioclient_mock, home_zone) -> None:
    aioclient_mock.get(AROUND_URL, json=load("around_point.json"))
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    await _setup(hass)

    state = hass.states.get("sensor.rare_birds_nearby")
    assert state is not None
    assert state.state == "5"
    attrs = state.attributes
    assert attrs["unit_of_measurement"] == "waarnemingen"
    assert attrs["icon"] == "mdi:bird"
    assert attrs["attribution"] == "Data: waarneming.nl / observation.org"
    assert attrs["radius_km"] == 10
    assert attrs["min_rarity"] == 3
    assert attrs["days"] == 3
    sightings = attrs["sightings"]
    assert len(sightings) == 5
    assert all(set(s) == SIGHTING_KEYS for s in sightings)
    times = [s["ts"] for s in sightings]
    assert all(isinstance(t, int) for t in times)
    assert times == sorted(times, reverse=True)
    assert isinstance(attrs["updated"], int)
    assert abs(attrs["updated"] - time.time()) < 60
    assert {s["region"] for s in sightings} == {
        "Rond huis",
        "Oostvaardersplassen - N2000",
    }
    # no raw API fields leak through
    assert "results" not in attrs
    assert len(str(sightings)) < 3072


async def test_max_sightings_caps_list_not_state(
    hass: HomeAssistant, aioclient_mock, home_zone
) -> None:
    aioclient_mock.get(AROUND_URL, json=load("around_point.json"))
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    await _setup(hass, max_sightings=2)
    state = hass.states.get("sensor.rare_birds_nearby")
    assert state.state == "5"
    assert len(state.attributes["sightings"]) == 2


async def test_areas_only(hass: HomeAssistant, aioclient_mock, home_zone) -> None:
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    await _setup(hass, use_home=False)
    state = hass.states.get("sensor.rare_birds_nearby")
    assert state.state == "3"
    assert state.attributes["radius_km"] is None
    assert aioclient_mock.call_count == 1


async def test_sightings_not_recorded(
    hass: HomeAssistant, aioclient_mock, home_zone
) -> None:
    aioclient_mock.get(AROUND_URL, json=load("around_point.json"))
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    entry = await _setup(hass)
    from custom_components.waarneming.sensor import WaarnemingSensor

    assert "sightings" in WaarnemingSensor._unrecorded_attributes
    assert "updated" in WaarnemingSensor._unrecorded_attributes
    assert entry.title == "Rare birds nearby"
