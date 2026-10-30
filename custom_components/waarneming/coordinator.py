"""Fetch, merge and filter waarneming.nl sightings."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .api import WaarnemingClient, WaarnemingError, WaarnemingRateLimited
from .const import (
    CONF_AREAS,
    CONF_DAYS,
    CONF_MAX_SIGHTINGS,
    CONF_MIN_RARITY,
    CONF_RADIUS_KM,
    CONF_SCAN_MINUTES,
    CONF_SPECIES_GROUP,
    CONF_USE_HOME,
    DEFAULT_DAYS,
    DEFAULT_MAX_SIGHTINGS,
    DEFAULT_MIN_RARITY,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_SPECIES_GROUP,
    DEFAULT_USE_HOME,
    DOMAIN,
    HOME_REGION,
    MIN_SCAN_MINUTES,
    RATE_LIMIT_BACKOFF,
)

_LOGGER = logging.getLogger(__name__)

type WaarnemingConfigEntry = ConfigEntry[WaarnemingCoordinator]


@dataclass(slots=True)
class WaarnemingData:
    """What the sensor shows."""

    total: int
    sightings: list[dict[str, Any]] = field(default_factory=list)


def home_location(hass: HomeAssistant) -> tuple[float, float] | None:
    """lat/lon of zone.home, read now (falls back to the core config)."""
    state = hass.states.get("zone.home")
    if state is not None:
        lat = state.attributes.get("latitude")
        lon = state.attributes.get("longitude")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    if hass.config.latitude is not None and hass.config.longitude is not None:
        return float(hass.config.latitude), float(hass.config.longitude)
    return None


def to_sighting(
    obs: dict[str, Any], region: str, home: tuple[float, float] | None
) -> dict[str, Any]:
    """One API observation → the small dict the attrList tile reads."""
    species = obs.get("species_detail") or {}
    certain = bool(obs.get("is_certain", True))
    name = species.get("name") or species.get("scientific_name") or "?"
    distance_km: float | None = None
    coords = (obs.get("point") or {}).get("coordinates")
    if home is not None and isinstance(coords, list) and len(coords) == 2:
        metres = distance(home[0], home[1], float(coords[1]), float(coords[0]))
        if metres is not None:
            distance_km = round(metres / 1000, 1)
    obs_date = obs.get("date") or ""
    obs_time = obs.get("time")
    return {
        "species": name if certain else f"{name} ?",
        "scientific": species.get("scientific_name"),
        "count": obs.get("number"),
        "place": (obs.get("location_detail") or {}).get("name"),
        "distance_km": distance_km,
        "observed_at": f"{obs_date}T{obs_time}:00" if obs_time else obs_date,
        "rarity": obs.get("rarity"),
        "certain": certain,
        "region": region,
        "url": obs.get("permalink"),
    }


def merge_sightings(
    sources: list[tuple[str, list[dict[str, Any]]]],
    min_rarity: int,
    home: tuple[float, float] | None,
) -> list[dict[str, Any]]:
    """Merge sources in order: dedupe by id (first source wins), drop escapes
    and anything under min_rarity, newest first."""
    seen: set[Any] = set()
    rows: list[dict[str, Any]] = []
    for region, results in sources:
        for obs in results:
            obs_id = obs.get("id")
            if obs_id is None or obs_id in seen:
                continue
            if obs.get("is_escape") or (obs.get("rarity") or 0) < min_rarity:
                continue
            seen.add(obs_id)
            rows.append(to_sighting(obs, region, home))
    rows.sort(key=lambda row: row["observed_at"] or "", reverse=True)
    return rows


class WaarnemingCoordinator(DataUpdateCoordinator[WaarnemingData]):
    """One fetch per source each interval."""

    config_entry: WaarnemingConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WaarnemingConfigEntry) -> None:
        minutes = max(
            MIN_SCAN_MINUTES,
            int(entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)),
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.client = WaarnemingClient(async_get_clientsession(hass))

    def _opt(self, key: str, default: Any) -> Any:
        return self.config_entry.options.get(key, default)

    @property
    def use_home(self) -> bool:
        return bool(self._opt(CONF_USE_HOME, DEFAULT_USE_HOME))

    @property
    def radius_km(self) -> int:
        return int(self._opt(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))

    @property
    def min_rarity(self) -> int:
        return int(self._opt(CONF_MIN_RARITY, DEFAULT_MIN_RARITY))

    @property
    def days(self) -> int:
        return int(self._opt(CONF_DAYS, DEFAULT_DAYS))

    @property
    def max_sightings(self) -> int:
        return int(self._opt(CONF_MAX_SIGHTINGS, DEFAULT_MAX_SIGHTINGS))

    async def _async_update_data(self) -> WaarnemingData:
        group = int(self._opt(CONF_SPECIES_GROUP, DEFAULT_SPECIES_GROUP))
        home = home_location(self.hass)
        sources: list[tuple[str, list[dict[str, Any]]]] = []
        try:
            if self.use_home:
                if home is None:
                    raise UpdateFailed("zone.home has no location")
                sources.append(
                    (
                        HOME_REGION,
                        await self.client.around_point(
                            home[0],
                            home[1],
                            self.radius_km * 1000,
                            self.days,
                            group,
                            self.min_rarity,
                        ),
                    )
                )
            date_after = dt_util.now().date() - timedelta(days=self.days)
            for area in self._opt(CONF_AREAS, []):
                sources.append(
                    (
                        str(area["name"]),
                        await self.client.area(
                            int(area["id"]), date_after, group, self.min_rarity
                        ),
                    )
                )
        except WaarnemingRateLimited as err:
            wait = err.retry_after or RATE_LIMIT_BACKOFF.total_seconds()
            raise UpdateFailed(
                f"waarneming.nl asks us to slow down; next try in {wait:.0f} s",
                retry_after=wait,
            ) from err
        except WaarnemingError as err:
            raise UpdateFailed(f"waarneming.nl not reachable: {err}") from err

        rows = merge_sightings(sources, self.min_rarity, home)
        return WaarnemingData(total=len(rows), sightings=rows[: self.max_sightings])
