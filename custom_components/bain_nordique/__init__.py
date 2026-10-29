"""Intégration Bain nordique : température de l'eau, prévisions de chauffe au bois, statistiques."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, CONF_OUTDOOR, CONF_WATER, DOMAIN, VERSION
from .coordinator import BainCoordinator

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER]

type BainConfigEntry = ConfigEntry[BainCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Sert la carte Lovelace et la fait charger par le frontend, sans réglage manuel."""
    if "http" not in hass.config.components or getattr(hass, "http", None) is None:
        return True
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        path = Path(__file__).parent / "frontend" / "bain-nordique-card.js"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(path), cache_headers=False)])
        if not await _async_register_resource(hass):
            add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")
    except Exception as err:  # noqa: BLE001 - la carte est un plus, pas un prérequis
        _LOGGER.warning("Carte Lovelace non chargée : %s", err)
    return True


async def _async_register_resource(hass: HomeAssistant) -> bool:
    """Déclare la carte comme ressource Lovelace et tient sa version à jour.

    L'application mobile charge les ressources de façon fiable, alors qu'elle
    peut garder en cache une page sans le script ajouté par add_extra_js_url.
    Retourne False si les ressources ne sont pas gérées par l'interface (mode YAML)."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    data = hass.data.get(LOVELACE_DATA)
    if data is None or data.resource_mode != "storage":
        return False
    resources = data.resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    url = f"{CARD_URL}?v={VERSION}"
    for item in resources.async_items():
        if item["url"].split("?")[0] == CARD_URL:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return True
    await resources.async_create_item({"res_type": "module", "url": url})
    return True


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
