"""Merge, dedupe, filter, sort; errors and back-off."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util.location import distance
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waarneming.const import DOMAIN, HOME_REGION
from custom_components.waarneming.coordinator import merge_sightings

from .conftest import AREA_URL, AROUND_URL, HOME, load

AREA = {"id": 701925, "name": "Oostvaardersplassen - N2000"}


def _sources() -> list:
    return [
        (HOME_REGION, load("around_point.json")["results"]),
        (AREA["name"], load("area_701925.json")["results"]),
    ]


def test_merge_dedupes_filters_and_sorts() -> None:
    rows = merge_sightings(_sources(), 3, HOME)
    assert [r["url"].rsplit("/", 2)[1] for r in rows] == [
        "9000012",  # 10-28 11:00
        "9000002",  # 10-28 07:40
        "9000001",  # 10-27 09:15
        "9000011",  # 10-27, no time
        "9000010",  # 10-26, in both sources: once, region of the first
    ]
    by_id = {r["url"].rsplit("/", 2)[1]: r for r in rows}
    assert by_id["9000010"]["region"] == HOME_REGION
    assert by_id["9000011"]["region"] == "Oostvaardersplassen - N2000"


def test_sighting_fields() -> None:
    by_id = {
        r["url"].rsplit("/", 2)[1]: r for r in merge_sightings(_sources(), 3, HOME)
    }
    assert by_id["9000001"] == {
        "species": "Klapekster",
        "scientific": "Lanius excubitor",
        "count": 1,
        "place": "Voorbeeldpolder",
        "distance_km": round(distance(HOME[0], HOME[1], 52.41, 5.31) / 1000, 1),
        "observed_at": "2026-10-27T09:15:00",
        "rarity": 3,
        "certain": True,
        "region": HOME_REGION,
        "url": "https://waarneming.nl/observation/9000001/",
    }
    assert by_id["9000002"]["species"] == "Roodpootvalk ?"
    assert by_id["9000002"]["certain"] is False
    assert by_id["9000011"]["observed_at"] == "2026-10-27"
    assert by_id["9000011"]["count"] == 2
    assert by_id["9000012"]["species"] == "Circus macrourus"  # no Dutch name
    assert by_id["9000012"]["distance_km"] is None  # no point


def test_rarity_threshold() -> None:
    rows = merge_sightings(_sources(), 4, HOME)
    assert {r["rarity"] for r in rows} == {4}
    rows = merge_sightings(_sources(), 1, HOME)
    assert any(r["species"] == "Kruisbek" for r in rows)
    assert not any(
        r["species"] == "Zwarte Zwaan" for r in rows
    )  # escape, always dropped


def test_no_home_no_distance() -> None:
    assert all(r["distance_km"] is None for r in merge_sightings(_sources(), 3, None))


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Rare birds nearby",
        data={},
        options={
            "use_home": True,
            "radius_km": 10,
            "areas": [AREA],
            "min_rarity": 3,
            "days": 3,
            "species_group": 1,
            "max_sightings": 10,
            **options,
        },
    )


async def test_one_fetch_per_source_with_params(
    hass: HomeAssistant, aioclient_mock, home_zone
) -> None:
    aioclient_mock.get(AROUND_URL, json=load("around_point.json"))
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    entry = _entry(radius_km=7, days=5, min_rarity=4)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 2
    around = aioclient_mock.mock_calls[0][1].query
    assert around["coordinates"] == "52.40000,5.30000"
    assert around["radius"] == "7000"
    assert around["days"] == "5"
    assert around["min_rarity"] == "4"
    assert around["species_group"] == "1"
    area = aioclient_mock.mock_calls[1][1].query
    assert area["rarity"] == "4"
    assert len(area["date_after"]) == 10
    assert hass.states.get("sensor.rare_birds_nearby").state == "3"


async def test_api_down_makes_entity_unavailable(
    hass: HomeAssistant, aioclient_mock, home_zone
) -> None:
    aioclient_mock.get(AROUND_URL, json=load("around_point.json"))
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.rare_birds_nearby").state == "5"

    aioclient_mock.clear_requests()
    aioclient_mock.get(AROUND_URL, status=503)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.rare_birds_nearby").state == "unavailable"


async def test_rate_limit_backs_off(
    hass: HomeAssistant, aioclient_mock, home_zone
) -> None:
    aioclient_mock.get(AROUND_URL, json=load("around_point.json"))
    aioclient_mock.get(AREA_URL, json=load("area_701925.json"))
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.get(AROUND_URL, status=429, headers={"Retry-After": "7200"})
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert (
        coordinator.last_exception.retry_after == 7200
    )  # HA schedules the next poll from this


async def test_setup_retries_when_down(
    hass: HomeAssistant, aioclient_mock, home_zone
) -> None:
    aioclient_mock.get(AROUND_URL, exc=TimeoutError())
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
