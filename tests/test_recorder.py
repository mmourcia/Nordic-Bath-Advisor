"""Relecture depuis le vrai recorder (états LazyState, pas des objets State)."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.bain_nordique.const import CONF_OUTDOOR, CONF_WATER, CONF_WIND, DOMAIN

WATER = "sensor.eau"
WEATHER = "weather.maison"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Le recorder doit démarrer avant hass : on remplace la fixture du conftest."""
    yield


async def test_replay_from_recorder(hass: HomeAssistant) -> None:
    for v in (33.2, 33.4, 33.6):
        hass.states.async_set(WATER, str(v), {"unit_of_measurement": "°C"})
        hass.states.async_set(WEATHER, "cloudy", {"temperature": 8.0 + v - 33,
                                                  "temperature_unit": "°C",
                                                  "wind_speed": 12.0, "wind_speed_unit": "km/h"})
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id=WATER,
                            data={CONF_WATER: WATER, CONF_OUTDOOR: WEATHER, CONF_WIND: WEATHER})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)   # la relecture tourne en fond

    coord = entry.runtime_data
    assert not coord.replaying
    assert coord.engine.last_ts is not None          # l'historique a bien été relu
    assert coord.data["advice"] != "Lecture de l'historique…"
    assert coord.card_info()["vent_kmh"] == 12.0
