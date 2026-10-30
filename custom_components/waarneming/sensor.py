"""The sightings sensor (same shape as the HA Paper rare-birds recipe)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, UNIT
from .coordinator import WaarnemingConfigEntry, WaarnemingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaarnemingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensor."""
    async_add_entities([WaarnemingSensor(entry.runtime_data)])


class WaarnemingSensor(CoordinatorEntity[WaarnemingCoordinator], SensorEntity):
    """Number of sightings; the newest ones in the `sightings` attribute."""

    _attr_has_entity_name = True
    _attr_name = None  # the entity takes the entry's name → sensor.rare_birds_nearby
    _attr_icon = "mdi:bird"
    _attr_native_unit_of_measurement = UNIT
    _attr_attribution = ATTRIBUTION
    # these change every poll and are only useful now; keep them out of history
    _unrecorded_attributes = frozenset({"sightings", "updated"})

    def __init__(self, coordinator: WaarnemingCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="waarneming.nl / observation.org",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://waarneming.nl/",
        )

    @property
    def native_value(self) -> int:
        return self.coordinator.data.total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coordinator = self.coordinator
        return {
            "sightings": coordinator.data.sightings,
            "radius_km": coordinator.radius_km if coordinator.use_home else None,
            "min_rarity": coordinator.min_rarity,
            "days": coordinator.days,
            "updated": coordinator.data.updated,
        }
