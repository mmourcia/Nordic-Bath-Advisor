"""Capteurs binaires : feu en cours, bain prêt, sonde hors de l'eau."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import BainEntity

BINARIES = (
    ("feu_en_cours", BinarySensorDeviceClass.HEAT, "in_fire"),
    ("bain_pret", None, "ready"),
    ("sonde_hors_eau", BinarySensorDeviceClass.PROBLEM, "probe_out"),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities(BainBinary(coord, key, dc, field) for key, dc, field in BINARIES)


class BainBinary(BainEntity, BinarySensorEntity):
    def __init__(self, coordinator, key: str, device_class, field: str) -> None:
        super().__init__(coordinator, key)
        self._attr_device_class = device_class
        self._field = field

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(self._field))

    @property
    def extra_state_attributes(self) -> dict | None:
        if self._field != "in_fire":
            return None
        f = self.coordinator.engine.fire
        return {"debut_montee": f.rise_start.isoformat() if f else None,
                "declare": bool(f and f.ignition) or self.coordinator.data.get("declared")}
