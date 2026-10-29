"""Relecture d'un export CSV par le coordinateur, comme depuis le recorder.

Ignoré sans export : BAIN_CSV=history.csv pytest tests/test_replay_csv.py
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bain_nordique.const import CONF_OUTDOOR, CONF_WATER, DOMAIN

CSV = os.environ.get("BAIN_CSV")
WATER = os.environ.get("BAIN_WATER", "sensor.sonde_bain_nordique_temperature_eau")
OUTDOOR = os.environ.get("BAIN_OUTDOOR", "sensor.terrasse_sonde_bain_nordique_temperature_exterieure")


def _load() -> dict[str, list[State]]:
    out: dict[str, list[State]] = {WATER: [], OUTDOOR: []}
    with open(CSV, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["entity_id"] in out:
                ts = datetime.fromisoformat(row["last_changed"].replace("Z", "+00:00"))
                out[row["entity_id"]].append(State(row["entity_id"], row["state"],
                                                   {"unit_of_measurement": "°C"},
                                                   last_changed=ts, last_updated=ts))
    return out


@pytest.mark.skipif(not CSV, reason="BAIN_CSV non défini")
async def test_replay(hass: HomeAssistant) -> None:
    hass.states.async_set(WATER, "33.4", {"unit_of_measurement": "°C"})
    hass.states.async_set(OUTDOOR, "10", {"unit_of_measurement": "°C"})
    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id=WATER,
                            data={CONF_WATER: WATER, CONF_OUTDOOR: OUTDOOR})
    entry.add_to_hass(hass)
    states = _load()
    with patch("custom_components.bain_nordique.coordinator.BainCoordinator._async_history",
               return_value=states), \
         patch("custom_components.bain_nordique.coordinator.BOOTSTRAP_DAYS", 400):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coord = entry.runtime_data
    st = coord.data["stats"]
    print("\nfeux", st["count"], "30 j", st["count_30d"], "temps moyens", st["mean_time"],
          "montée", st["mean_rate"], "k", coord.params.k_fit(),
          "maintien", coord.params.hold_low, coord.params.hold_high, "\n", coord.data["advice"])
    assert st["count"] >= 5
    assert coord.params.hold_low is not None
