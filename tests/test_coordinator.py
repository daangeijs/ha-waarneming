"""Merge, dedupe, filter, sort; errors and back-off."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util.location import distance
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.waarneming.const import DOMAIN, HOME_REGION
from custom_components.waarneming.coordinator import (
    make_subtitle,
    make_title,
    merge_sightings,
    observed,
    to_sighting,
)

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
        "9000011",  # 10-27, no time: counts as 12:00
        "9000001",  # 10-27 09:15
        "9000010",  # 10-26, in both sources: once, region of the first
    ]
    by_id = {r["url"].rsplit("/", 2)[1]: r for r in rows}
    assert by_id["9000010"]["region"] == HOME_REGION
    assert by_id["9000011"]["region"] == "Oostvaardersplassen - N2000"


def test_sighting_fields() -> None:
    by_id = {
        r["url"].rsplit("/", 2)[1]: r for r in merge_sightings(_sources(), 3, HOME)
    }
    km = round(distance(HOME[0], HOME[1], 52.41, 5.31) / 1000, 1)
    assert by_id["9000001"] == {
        "species": "Klapekster",
        "scientific": "Lanius excubitor",
        "count": 1,
        "place": "Voorbeeldpolder",
        "distance_km": km,
        "observed_at": "2026-10-27T09:15:00+01:00",
        "rarity": 3,
        "certain": True,
        "region": HOME_REGION,
        "url": "https://waarneming.nl/observation/9000001/",
        "title": "Klapekster",
        "subtitle": f"Voorbeeldpolder · {km:.1f} km".replace(".", ","),
        "ts": 1793088900,  # 2026-10-27 08:15 UTC
    }
    assert by_id["9000002"]["species"] == "Roodpootvalk ?"
    assert by_id["9000002"]["title"] == "Roodpootvalk ?"
    assert by_id["9000002"]["certain"] is False
    assert by_id["9000011"]["observed_at"] == "2026-10-27"
    assert by_id["9000011"]["ts"] == 1793098800  # 12:00 local = 11:00 UTC
    assert by_id["9000011"]["count"] == 2
    assert by_id["9000011"]["title"].startswith("2× ")
    assert by_id["9000012"]["species"] == "Circus macrourus"  # no Dutch name
    assert by_id["9000012"]["distance_km"] is None  # no point


def _obs(**over) -> dict:
    obs = {
        "id": 1,
        "species_detail": {"name": "Kraanvogel", "scientific_name": "Grus grus"},
        "date": "2026-10-25",
        "time": "09:00",
        "number": 1,
        "is_certain": True,
        "location_detail": {"name": "Heidebos"},
        "point": None,
        "rarity": 3,
    }
    obs.update(over)
    return obs


def test_ts_and_offset_around_dst_end() -> None:
    # 2026-10-25 is the last Sunday of October: 03:00 CEST becomes 02:00 CET.
    assert observed("2026-10-25", "01:30") == (
        "2026-10-25T01:30:00+02:00",
        1792884600,  # 2026-10-24 23:30 UTC
    )
    assert observed("2026-10-25", "03:30") == (
        "2026-10-25T03:30:00+01:00",
        1792895400,  # 02:30 UTC
    )
    # 02:30 happens twice that night; we take the first (summer time).
    assert observed("2026-10-25", "02:30") == (
        "2026-10-25T02:30:00+02:00",
        1792888200,  # 00:30 UTC
    )
    # the day before and after: one hour shift in the offset
    assert observed("2026-10-24", "12:00")[0].endswith("+02:00")
    assert observed("2026-10-26", "12:00")[0].endswith("+01:00")


def test_ts_date_only_and_bad_input() -> None:
    # no time recorded: observed_at stays the bare date, ts is 12:00 local (CET)
    assert observed("2026-10-25", None) == ("2026-10-25", 1792926000)
    # 12:00 on the spring-forward day is summer time: 10:00 UTC
    assert observed("2026-03-29", None) == ("2026-03-29", 1774778400)
    assert observed("2026-10-25", "09:15:30")[0] == "2026-10-25T09:15:30+01:00"
    assert observed("", None) == ("", None)
    assert observed("2026-10-25", "late")[1] == 1792926000  # bad time → noon


def test_title() -> None:
    assert make_title("Kraanvogel", 1) == "Kraanvogel"
    assert make_title("Kraanvogel", 3) == "3× Kraanvogel"
    assert make_title("Kraanvogel ?", 12) == "12× Kraanvogel ?"
    assert make_title("Kraanvogel", None) == "Kraanvogel"
    assert make_title("Kraanvogel", 0) == "Kraanvogel"
    row = to_sighting(_obs(number=3, is_certain=False), HOME_REGION, None)
    assert row["title"] == "3× Kraanvogel ?"
    assert row["species"] == "Kraanvogel ?"
    assert row["count"] == 3


def test_subtitle() -> None:
    assert make_subtitle("Heidebos", 3.2, HOME_REGION) == "Heidebos · 3,2 km"
    assert make_subtitle("Heidebos", 12.0, "Voorbeeldgebied") == "Heidebos · 12,0 km"
    # area sighting, no home distance: the area name, unless it is the place itself
    assert make_subtitle("Heidebos", None, "Voorbeeldgebied") == (
        "Heidebos · Voorbeeldgebied"
    )
    assert make_subtitle("Voorbeeldgebied", None, "Voorbeeldgebied") == (
        "Voorbeeldgebied"
    )
    # home sighting without a point: just the place
    assert make_subtitle("Heidebos", None, HOME_REGION) == "Heidebos"
    assert make_subtitle(None, None, "Voorbeeldgebied") == "Voorbeeldgebied"
    assert make_subtitle(None, 1.5, "Voorbeeldgebied") == "Voorbeeldgebied · 1,5 km"


def test_area_sighting_without_home() -> None:
    point = {"type": "Point", "coordinates": [5.31, 52.41]}
    row = to_sighting(_obs(point=point), "Oostvaardersplassen - N2000", None)
    assert row["distance_km"] is None
    assert row["subtitle"] == "Heidebos · Oostvaardersplassen - N2000"
    with_home = to_sighting(_obs(point=point), "Oostvaardersplassen - N2000", HOME)
    assert with_home["subtitle"].startswith("Heidebos · ")
    assert with_home["subtitle"].endswith(" km")
    assert "," in with_home["subtitle"]


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
