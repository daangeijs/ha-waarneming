"""Constants for the Waarneming integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "waarneming"

API_BASE: Final = "https://waarneming.nl/api/v1"
USER_AGENT: Final = (
    "HomeAssistant-Waarneming/0.1.0 (+https://github.com/daangeijs/ha-waarneming)"
)
ATTRIBUTION: Final = "Data: waarneming.nl / observation.org"

CONF_USE_HOME: Final = "use_home"
CONF_RADIUS_KM: Final = "radius_km"
CONF_AREAS: Final = "areas"  # list of {"id": int, "name": str}
CONF_ADD_AREAS: Final = "add_areas"  # free text in the flows: ids or URLs
CONF_MIN_RARITY: Final = "min_rarity"
CONF_DAYS: Final = "days"
CONF_SPECIES_GROUP: Final = "species_group"
CONF_MAX_SIGHTINGS: Final = "max_sightings"
CONF_SCAN_MINUTES: Final = "scan_minutes"

DEFAULT_NAME: Final = "Rare birds nearby"
DEFAULT_USE_HOME: Final = True
DEFAULT_RADIUS_KM: Final = 10
DEFAULT_MIN_RARITY: Final = 3
DEFAULT_DAYS: Final = 3
DEFAULT_SPECIES_GROUP: Final = 1  # birds
DEFAULT_MAX_SIGHTINGS: Final = 10
DEFAULT_SCAN_MINUTES: Final = 30

MIN_RADIUS_KM: Final = 1
MAX_RADIUS_KM: Final = 10  # the around-point route caps radius at 10 000 m
MIN_DAYS: Final = 1
MAX_DAYS: Final = 14
MIN_MAX_SIGHTINGS: Final = 1
MAX_MAX_SIGHTINGS: Final = 25  # one page of each source (limit=25)
MIN_SCAN_MINUTES: Final = (
    15  # never poll faster than this (agreed with observation.org)
)
MAX_SCAN_MINUTES: Final = 1440

PAGE_LIMIT: Final = 25
REQUEST_TIMEOUT: Final = timedelta(seconds=30)
RATE_LIMIT_BACKOFF: Final = timedelta(hours=1)  # used when a 429 has no Retry-After

HOME_REGION: Final = "Rond huis"  # `region` of sightings from the home-zone source
UNIT: Final = "waarnemingen"
