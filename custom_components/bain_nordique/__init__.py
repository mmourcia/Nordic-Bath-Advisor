"""Intégration Bain nordique : température de l'eau, prévisions de chauffe au bois, statistiques."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_OUTDOOR, CONF_WATER
from .coordinator import BainCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER]

type BainConfigEntry = ConfigEntry[BainCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BainConfigEntry) -> bool:
    coordinator = BainCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: BainConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BainConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_shutdown_save()
    return ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v0.x → 1.0 : on garde la sonde d'eau et la température extérieure."""
    if entry.version == 1:
        data = {CONF_WATER: entry.data[CONF_WATER]}
        if entry.data.get(CONF_OUTDOOR):
            data[CONF_OUTDOOR] = entry.data[CONF_OUTDOOR]
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
