"""Config and options flow for Waarneming."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .api import WaarnemingClient, WaarnemingError, WaarnemingNotFound, parse_area_list
from .const import (
    CONF_ADD_AREAS,
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
    DEFAULT_NAME,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_SPECIES_GROUP,
    DEFAULT_USE_HOME,
    DOMAIN,
    MAX_DAYS,
    MAX_MAX_SIGHTINGS,
    MAX_RADIUS_KM,
    MAX_SCAN_MINUTES,
    MIN_DAYS,
    MIN_MAX_SIGHTINGS,
    MIN_RADIUS_KM,
    MIN_SCAN_MINUTES,
)
from .coordinator import WaarnemingConfigEntry

Area = dict[str, Any]  # {"id": int, "name": str}


def _number(
    lo: int, hi: int, mode: NumberSelectorMode, unit: str | None = None
) -> NumberSelector:
    config = NumberSelectorConfig(min=lo, max=hi, step=1, mode=mode)
    if unit is not None:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


RARITY_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=["1", "2", "3", "4"],
        translation_key="min_rarity",
        mode=SelectSelectorMode.DROPDOWN,
    )
)
AREA_TEXT = TextSelector(TextSelectorConfig(multiline=True))


def _filter_fields(values: dict[str, Any]) -> dict[vol.Marker, Any]:
    """Schema keys shared by both flows (defaults from `values`)."""
    return {
        vol.Required(
            CONF_USE_HOME, default=values.get(CONF_USE_HOME, DEFAULT_USE_HOME)
        ): BooleanSelector(),
        vol.Required(
            CONF_RADIUS_KM, default=values.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
        ): _number(MIN_RADIUS_KM, MAX_RADIUS_KM, NumberSelectorMode.SLIDER, "km"),
    }


def _tail_fields(values: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        vol.Required(
            CONF_MIN_RARITY,
            default=str(values.get(CONF_MIN_RARITY, DEFAULT_MIN_RARITY)),
        ): RARITY_SELECTOR,
        vol.Required(CONF_DAYS, default=values.get(CONF_DAYS, DEFAULT_DAYS)): _number(
            MIN_DAYS, MAX_DAYS, NumberSelectorMode.SLIDER
        ),
        vol.Required(
            CONF_SPECIES_GROUP,
            default=values.get(CONF_SPECIES_GROUP, DEFAULT_SPECIES_GROUP),
        ): _number(1, 99, NumberSelectorMode.BOX),
        vol.Required(
            CONF_MAX_SIGHTINGS,
            default=values.get(CONF_MAX_SIGHTINGS, DEFAULT_MAX_SIGHTINGS),
        ): _number(MIN_MAX_SIGHTINGS, MAX_MAX_SIGHTINGS, NumberSelectorMode.BOX),
    }


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Selectors give floats/strings; store ints."""
    out: dict[str, Any] = {CONF_USE_HOME: bool(user_input[CONF_USE_HOME])}
    for key in (
        CONF_RADIUS_KM,
        CONF_MIN_RARITY,
        CONF_DAYS,
        CONF_SPECIES_GROUP,
        CONF_MAX_SIGHTINGS,
    ):
        out[key] = int(float(user_input[key]))
    if CONF_SCAN_MINUTES in user_input:
        out[CONF_SCAN_MINUTES] = max(
            MIN_SCAN_MINUTES, int(float(user_input[CONF_SCAN_MINUTES]))
        )
    return out


def regions_text(areas: list[Area]) -> str:
    """Markdown list of regions for the confirm step."""
    return "\n".join(f"- {a['name']} ({a['id']})" for a in areas) or "-"


async def async_resolve_areas(
    hass: HomeAssistant, keep: list[Area], text: str | None
) -> tuple[list[Area], list[Area], dict[str, str], dict[str, str]]:
    """Parse the add-areas text, look up the names of new ids.

    Returns (all areas, newly added areas, errors, description placeholders).
    """
    ids, bad = parse_area_list(text)
    if bad:
        return keep, [], {CONF_ADD_AREAS: "invalid_area"}, {"area": bad[0]}
    known = {int(a["id"]) for a in keep}
    client = WaarnemingClient(async_get_clientsession(hass))
    added: list[Area] = []
    for area_id in ids:
        if area_id in known:
            continue
        try:
            name = await client.area_name(area_id)
        except WaarnemingNotFound:
            return keep, [], {CONF_ADD_AREAS: "area_not_found"}, {"area": str(area_id)}
        except WaarnemingError:
            return keep, [], {"base": "cannot_connect"}, {}
        added.append({"id": area_id, "name": name})
        known.add(area_id)
    return keep + added, added, {}, {}


class WaarnemingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Waarneming sensor."""

    VERSION = 1

    def __init__(self) -> None:
        self._title = DEFAULT_NAME
        self._options: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(entry: WaarnemingConfigEntry) -> WaarnemingOptionsFlow:
        return WaarnemingOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"area": ""}
        if user_input is not None:
            areas, _, errors, found = await async_resolve_areas(
                self.hass, [], user_input.get(CONF_ADD_AREAS)
            )
            placeholders.update(found)
            if not errors and not user_input[CONF_USE_HOME] and not areas:
                errors["base"] = "no_source"
            if not errors:
                self._title = user_input[CONF_NAME].strip() or DEFAULT_NAME
                self._options = {**_clean(user_input), CONF_AREAS: areas}
                if areas:
                    return await self.async_step_confirm()
                return self._create()

        values = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=values.get(CONF_NAME, DEFAULT_NAME)
                ): str,
                **_filter_fields(values),
                vol.Optional(
                    CONF_ADD_AREAS,
                    description={"suggested_value": values.get(CONF_ADD_AREAS)},
                ): AREA_TEXT,
                **_tail_fields(values),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the area names found, then create the entry."""
        if user_input is not None:
            return self._create()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "regions": regions_text(self._options[CONF_AREAS])
            },
        )

    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._title, data={}, options=self._options
        )


class WaarnemingOptionsFlow(OptionsFlowWithReload):
    """Change filters; add or remove areas."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current: dict[str, Any] = dict(self.config_entry.options)
        existing: list[Area] = list(current.get(CONF_AREAS, []))
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"area": "", "regions": regions_text(existing)}

        if user_input is not None:
            keep_ids = set(user_input.get(CONF_AREAS, []))
            keep = [a for a in existing if str(a["id"]) in keep_ids]
            areas, added, errors, found = await async_resolve_areas(
                self.hass, keep, user_input.get(CONF_ADD_AREAS)
            )
            placeholders.update(found)
            if not errors and not user_input[CONF_USE_HOME] and not areas:
                errors["base"] = "no_source"
            if not errors:
                self._options = {**_clean(user_input), CONF_AREAS: areas}
                if added:
                    return await self.async_step_confirm()
                return self.async_create_entry(data=self._options)

        values: dict[str, Any] = {**current, **(user_input or {})}
        fields: dict[vol.Marker, Any] = dict(_filter_fields(values))
        if existing:
            fields[
                vol.Optional(
                    CONF_AREAS,
                    default=[str(a["id"]) for a in existing]
                    if user_input is None
                    else user_input.get(CONF_AREAS, []),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=str(a["id"]), label=f"{a['name']} ({a['id']})"
                        )
                        for a in existing
                    ],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        fields[
            vol.Optional(
                CONF_ADD_AREAS,
                description={"suggested_value": (user_input or {}).get(CONF_ADD_AREAS)},
            )
        ] = AREA_TEXT
        fields.update(_tail_fields(values))
        fields[
            vol.Required(
                CONF_SCAN_MINUTES,
                default=values.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
            )
        ] = _number(MIN_SCAN_MINUTES, MAX_SCAN_MINUTES, NumberSelectorMode.BOX, "min")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the names of all regions (new ones included), then save."""
        if user_input is not None:
            return self.async_create_entry(data=self._options)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "regions": regions_text(self._options[CONF_AREAS])
            },
        )
