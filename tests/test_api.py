"""Area id parsing and area name lookup."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.waarneming.api import (
    WaarnemingClient,
    WaarnemingNotFound,
    parse_area_id,
    parse_area_list,
)

from .conftest import AREA_URL, GEOJSON_URL, load


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("701925", 701925),
        (" 701925 ", 701925),
        ("https://waarneming.nl/locations/701925/", 701925),
        (
            "https://waarneming.nl/locations/701925/observations/?date=2026-10-28",
            701925,
        ),
        ("waarneming.nl/locations/701925", 701925),
        ("https://observation.org/locations/701925/", 701925),
        ("Oostvaardersplassen", None),
        ("https://waarneming.nl/species/52/", None),
    ],
)
def test_parse_area_id(text: str, expected: int | None) -> None:
    assert parse_area_id(text) == expected


def test_parse_area_list() -> None:
    ids, bad = parse_area_list(
        "701925\nhttps://waarneming.nl/locations/800201/, 701925 ; nonsense"
    )
    assert ids == [701925, 800201]
    assert bad == ["nonsense"]
    assert parse_area_list(None) == ([], [])


async def test_area_name_from_own_observation(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(AREA_URL, json=load("area_name_self.json"))
    client = WaarnemingClient(async_get_clientsession(hass))
    assert await client.area_name(701925) == "Oostvaardersplassen - N2000"
    assert aioclient_mock.call_count == 1


async def test_area_name_via_geojson(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(AREA_URL, json=load("area_name_sub.json"))
    aioclient_mock.get(GEOJSON_URL, json=load("geojson_701925.json"))
    client = WaarnemingClient(async_get_clientsession(hass))
    assert await client.area_name(701925) == "Oostvaardersplassen - N2000"
    # the geojson lookup uses lat,lon of an observation in the area
    assert aioclient_mock.mock_calls[1][1].query["coordinates"] == "52.440000,5.370000"


async def test_area_name_fallback_most_common(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(AREA_URL, json=load("area_name_sub.json"))
    aioclient_mock.get(GEOJSON_URL, status=500)
    client = WaarnemingClient(async_get_clientsession(hass))
    assert await client.area_name(701925) == "Oostvaardersplassen - Kijkhut"


async def test_area_name_empty_area(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(AREA_URL, json={"count": 0, "results": []})
    client = WaarnemingClient(async_get_clientsession(hass))
    assert await client.area_name(701925) == "Gebied 701925"


async def test_area_name_unknown_id(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{AREA_URL.replace('701925', '999999999')}", status=404)
    client = WaarnemingClient(async_get_clientsession(hass))
    with pytest.raises(WaarnemingNotFound):
        await client.area_name(999999999)


async def test_requests_send_dutch_and_user_agent(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(AREA_URL, json=load("area_name_self.json"))
    client = WaarnemingClient(async_get_clientsession(hass))
    await client.area_name(701925)
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["Accept-Language"] == "nl"
    assert "github.com/daangeijs/ha-waarneming" in headers["User-Agent"]
