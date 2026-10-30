"""Small client for the public waarneming.nl / observation.org API."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Any

import aiohttp

from .const import API_BASE, PAGE_LIMIT, REQUEST_TIMEOUT, USER_AGENT

_AREA_URL_RE = re.compile(r"/locations/(\d+)")
_SPLIT_RE = re.compile(r"[\s,;]+")


class WaarnemingError(Exception):
    """The API could not be reached or answered with an error."""


class WaarnemingNotFound(WaarnemingError):
    """The API answered 404 (e.g. an unknown area id)."""


class WaarnemingRateLimited(WaarnemingError):
    """The API answered 429."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate limited by waarneming.nl")
        self.retry_after = retry_after


def parse_area_id(text: str) -> int | None:
    """Turn '701925' or 'https://waarneming.nl/locations/701925/' into 701925."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    if match := _AREA_URL_RE.search(text):
        return int(match.group(1))
    return None


def parse_area_list(text: str | None) -> tuple[list[int], list[str]]:
    """Split free text into area ids; return (ids in order, unparseable tokens)."""
    ids: list[int] = []
    bad: list[str] = []
    for token in _SPLIT_RE.split(text or ""):
        if not token:
            continue
        area_id = parse_area_id(token)
        if area_id is None:
            bad.append(token)
        elif area_id not in ids:
            ids.append(area_id)
    return ids, bad


class WaarnemingClient:
    """Anonymous GETs on the waarneming.nl API, Dutch species names."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{API_BASE}/{path}"
        headers = {"Accept-Language": "nl", "User-Agent": USER_AGENT}
        try:
            async with self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT.total_seconds()),
            ) as resp:
                if resp.status == 429:
                    retry: float | None = None
                    if (value := resp.headers.get("Retry-After", "")).isdigit():
                        retry = float(value)
                    raise WaarnemingRateLimited(retry)
                if resp.status == 404:
                    raise WaarnemingNotFound(f"not found: {path}")
                if resp.status >= 400:
                    raise WaarnemingError(f"HTTP {resp.status} for {path}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise WaarnemingError(f"{type(err).__name__} for {path}") from err

    @staticmethod
    def _results(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return [r for r in payload["results"] if isinstance(r, dict)]
        raise WaarnemingError("unexpected answer (no results list)")

    async def around_point(
        self,
        lat: float,
        lon: float,
        radius_m: int,
        days: int,
        species_group: int,
        min_rarity: int,
    ) -> list[dict[str, Any]]:
        """Observations within radius_m of a point over the last `days`."""
        payload = await self._get(
            "observations/around-point/",
            {
                "coordinates": f"{lat:.5f},{lon:.5f}",
                "radius": radius_m,
                "days": days,
                "species_group": species_group,
                "min_rarity": min_rarity,
                "limit": PAGE_LIMIT,
            },
        )
        return self._results(payload)

    async def area(
        self, area_id: int, date_after: date, species_group: int, min_rarity: int
    ) -> list[dict[str, Any]]:
        """Observations in an area (and its sub-areas) since date_after."""
        payload = await self._get(
            f"locations/{area_id}/observations/",
            {
                "species_group": species_group,
                "rarity": min_rarity,  # a minimum on this route
                "date_after": date_after.isoformat(),
                "limit": PAGE_LIMIT,
            },
        )
        return self._results(payload)

    async def area_name(self, area_id: int) -> str:
        """Find an area's name; raises WaarnemingNotFound for an unknown id.

        `locations/<id>/` needs a login, so the name comes from the area's own
        observations: an observation made at the area itself carries it in
        location_detail. Otherwise ask the geojson route at an observation's
        point, then fall back to the most common place name.
        """
        results = self._results(
            await self._get(f"locations/{area_id}/observations/", {"limit": PAGE_LIMIT})
        )
        names: Counter[str] = Counter()
        point: list[float] | None = None
        for obs in results:
            detail = obs.get("location_detail") or {}
            name = detail.get("name")
            if detail.get("id") == area_id and name:
                return str(name)
            if name:
                names[str(name)] += 1
            coords = (obs.get("point") or {}).get("coordinates")
            if point is None and isinstance(coords, list) and len(coords) == 2:
                point = coords
        if point is not None:
            try:
                geo = await self._get(
                    "locations/geojson/",
                    {"coordinates": f"{point[1]:.6f},{point[0]:.6f}"},
                )
            except WaarnemingError:  # the name is a nicety; never fail on it
                geo = None
            for feature in (geo or {}).get("features") or []:
                props = feature.get("properties") or {}
                if props.get("id") == area_id and props.get("title"):
                    return str(props["title"])
        if names:
            return names.most_common(1)[0][0]
        return f"Gebied {area_id}"
