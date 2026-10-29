"""Configuration via l'interface : sonde d'eau, température extérieure, vent."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_OUTDOOR, CONF_WATER, CONF_WIND, DOMAIN

_WATER = EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature"))
_OUTDOOR = EntitySelector(EntitySelectorConfig(filter=[
    {"domain": "sensor", "device_class": "temperature"}, {"domain": "weather"}]))
_WIND = EntitySelector(EntitySelectorConfig(filter=[
    {"domain": "sensor", "device_class": "wind_speed"}, {"domain": "weather"}]))


def _schema(defaults: dict[str, Any], with_water: bool) -> vol.Schema:
    fields: dict = {}
    if with_water:
        fields[vol.Required(CONF_WATER, default=defaults.get(CONF_WATER, vol.UNDEFINED))] = _WATER
    fields[vol.Required(CONF_OUTDOOR, default=defaults.get(CONF_OUTDOOR, vol.UNDEFINED))] = _OUTDOOR
    wind = defaults.get(CONF_WIND)
    fields[vol.Optional(CONF_WIND, description={"suggested_value": wind} if wind else None)] = _WIND
    return vol.Schema(fields)


class BainConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_WATER])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Bain nordique", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}, True))

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return BainOptionsFlow()


class BainOptionsFlow(OptionsFlow):
    """Changer la température extérieure ou le vent sans tout réinstaller."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=_schema(current, False))
