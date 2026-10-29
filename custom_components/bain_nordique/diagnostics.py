"""Diagnostics : paramètres appris et feux, à joindre à un ticket."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    coord = entry.runtime_data
    return {"config": {**entry.data, **entry.options}, "store": coord._snapshot(),
            "fire_in_progress": bool(coord.engine.fire)}
