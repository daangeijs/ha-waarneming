"""Fetch, merge and filter waarneming.nl sightings."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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

# waarneming.nl gives date and time as Dutch local wall-clock time, without an offset.
API_TZ = ZoneInfo("Europe/Amsterdam")
# A date-only sighting (no time recorded) gets this local time for `ts` and sorting.
DATE_ONLY_TIME = time(12, 0)

type WaarnemingConfigEntry = ConfigEntry[WaarnemingCoordinator]


@dataclass(slots=True)
class WaarnemingData:
    """What the sensor shows."""

    total: int
    sightings: list[dict[str, Any]] = field(default_factory=list)
    updated: int | None = None  # epoch seconds of the successful fetch


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


def observed(obs_date: str, obs_time: str | None) -> tuple[str, int | None]:
    """API date + time (Dutch local) → (`observed_at`, `ts`).

    `observed_at` is ISO with the UTC offset ("2026-10-27T09:15:00+01:00"), or the
    bare date when no time was recorded. `ts` is Unix epoch seconds (UTC). A
    date-only sighting is placed at 12:00 local, a guess in the middle of the day.
    On the night the clocks go back the hour 02:00-03:00 happens twice; zoneinfo's
    default (fold=0) takes the first one, summer time.
    """
    try:
        day = date.fromisoformat(obs_date)
    except ValueError:
        return obs_date, None
    if obs_time:
        try:
            clock = time.fromisoformat(obs_time)
        except ValueError:
            clock = None
        if clock is not None:
            local = datetime.combine(day, clock.replace(tzinfo=None), API_TZ)
            return local.isoformat(), int(local.timestamp())
    local = datetime.combine(day, DATE_ONLY_TIME, API_TZ)
    return obs_date, int(local.timestamp())


def format_km(km: float) -> str:
    """3.2 → "3,2 km" (Dutch decimal comma)."""
    return f"{km:.1f}".replace(".", ",") + " km"


def make_title(species: str, count: Any) -> str:
    """Count prefix: "Kraanvogel ?" with count 3 → "3× Kraanvogel ?"."""
    if isinstance(count, int) and count > 1:
        return f"{count}× {species}"
    return species


def make_subtitle(place: str | None, distance_km: float | None, region: str) -> str:
    """Place and distance, or place and region when there is no distance."""
    where = place or region
    if distance_km is not None:
        return (
            f"{where} · {format_km(distance_km)}" if where else format_km(distance_km)
        )
    if place and region and region != place and region != HOME_REGION:
        return f"{place} · {region}"
    return where or ""


def to_sighting(
    obs: dict[str, Any], region: str, home: tuple[float, float] | None
) -> dict[str, Any]:
    """One API observation → the small dict the attrList tile reads.

    `title`, `subtitle` and `ts` are display-ready so the e-paper device only prints.
    """
    species = obs.get("species_detail") or {}
    certain = bool(obs.get("is_certain", True))
    name = species.get("name") or species.get("scientific_name") or "?"
    shown = name if certain else f"{name} ?"
    distance_km: float | None = None
    coords = (obs.get("point") or {}).get("coordinates")
    if home is not None and isinstance(coords, list) and len(coords) == 2:
        metres = distance(home[0], home[1], float(coords[1]), float(coords[0]))
        if metres is not None:
            distance_km = round(metres / 1000, 1)
    observed_at, ts = observed(obs.get("date") or "", obs.get("time"))
    count = obs.get("number")
    place = (obs.get("location_detail") or {}).get("name")
    return {
        "species": shown,
        "scientific": species.get("scientific_name"),
        "count": count,
        "place": place,
        "distance_km": distance_km,
        "observed_at": observed_at,
        "rarity": obs.get("rarity"),
        "certain": certain,
        "region": region,
        "url": obs.get("permalink"),
        "title": make_title(shown, count),
        "subtitle": make_subtitle(place, distance_km, region),
        "ts": ts,
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
    rows.sort(key=lambda row: row["ts"] or 0, reverse=True)
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
        return WaarnemingData(
            total=len(rows),
            sightings=rows[: self.max_sightings],
            updated=int(dt_util.utcnow().timestamp()),
        )
