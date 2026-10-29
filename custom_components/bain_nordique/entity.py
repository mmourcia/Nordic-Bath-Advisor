"""Entité de base."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import BainCoordinator


class BainEntity(CoordinatorEntity[BainCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BainCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Bain nordique", manufacturer="Nordic Bath Advisor",
            model="Prévision de chauffe au bois", sw_version=VERSION,
        )
