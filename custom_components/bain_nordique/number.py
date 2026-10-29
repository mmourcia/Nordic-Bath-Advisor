"""Réglage : température visée."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import BainEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([TargetNumber(entry.runtime_data)])


class TargetNumber(BainEntity, NumberEntity):
    _attr_icon = "mdi:thermometer-check"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 30.0
    _attr_native_max_value = 44.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "cible")

    @property
    def native_value(self) -> float:
        return self.coordinator.target

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_target(value)
