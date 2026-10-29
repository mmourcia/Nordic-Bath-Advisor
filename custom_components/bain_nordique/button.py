"""Boutons : feu allumé, pas de feu, réapprendre depuis l'historique."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import BainEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    async_add_entities([FireButton(coord), CancelButton(coord), RelearnButton(coord)])


class FireButton(BainEntity, ButtonEntity):
    """Signale l'allumage : apprend le délai allumage → montée et accélère la détection."""

    _attr_icon = "mdi:fire"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "feu_allume")

    async def async_press(self) -> None:
        self.coordinator.declare_fire()


class CancelButton(BainEntity, ButtonEntity):
    """Fausse détection ou déclaration par erreur."""

    _attr_icon = "mdi:fire-off"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "pas_de_feu")

    async def async_press(self) -> None:
        self.coordinator.cancel_fire()


class RelearnButton(BainEntity, ButtonEntity):
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "reapprendre")

    async def async_press(self) -> None:
        await self.coordinator.async_relearn()
