"""La carte est déclarée comme ressource Lovelace et sa version est tenue à jour."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.bain_nordique import _async_register_resource
from custom_components.bain_nordique.const import CARD_URL, VERSION


async def test_resource_created_then_updated(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    resources = hass.data[LOVELACE_DATA].resources
    await resources.async_load()
    resources.loaded = True
    await resources.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.1"})

    assert await _async_register_resource(hass)
    assert await _async_register_resource(hass)          # idempotent
    urls = [r["url"] for r in resources.async_items() if r["url"].startswith(CARD_URL)]
    assert urls == [f"{CARD_URL}?v={VERSION}"]
