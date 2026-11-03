"""Consommation et coût du maintien électrique."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bain_nordique.const import (
    CONF_OUTDOOR,
    CONF_POWER,
    CONF_PRICE,
    CONF_WATER,
    DOMAIN,
)
from custom_components.bain_nordique.energy import HeaterMeter


def _midnight(days_ago: int = 0):
    return dt_util.start_of_local_day() - timedelta(days=days_ago)


def test_power_integrated_per_day_and_average() -> None:
    m = HeaterMeter(source="sensor.prise_puissance")
    t = _midnight(3) + timedelta(hours=12)              # premier jour partiel : ignoré
    m.set_power(t, 3000)
    end = _midnight(0) + timedelta(hours=1)
    while t < end:                                      # 3 kW un quart du temps
        t += timedelta(minutes=1)
        m.set_power(t, 3000 if t.minute < 15 else 0)
        m.tick(t, 5.0)
    s = m.summary(end, 0.25)
    assert s["days_counted"] == 2 and not s["estimate"]
    assert abs(s["per_day_kwh"] - 18.0) < 0.2           # 3 kW × 6 h
    assert abs(s["per_day_cost"] - 4.5) < 0.05
    assert s["days"][-1]["ext"] == 5.0
    assert abs(s["kwh_today"] - 0.75) < 0.06


def test_counter_reset_and_gap() -> None:
    m = HeaterMeter(source="sensor.prise_energie")
    t = _midnight(0) + timedelta(hours=1)
    m.add_counter(t, 10.0)
    m.add_counter(t + timedelta(hours=1), 10.5)
    m.add_counter(t + timedelta(hours=2), 0.2)          # prise redémarrée
    assert abs(m.summary(t + timedelta(hours=2), 0.2)["kwh_today"] - 0.7) < 1e-6
    # une coupure de plus d'une heure n'est pas intégrée
    p = HeaterMeter(source="sensor.prise_puissance")
    p.set_power(t, 3000)
    p.set_power(t + timedelta(hours=3), 0)
    assert p.summary(t + timedelta(hours=3), 0.2)["kwh_today"] == 0


def test_estimate_before_first_full_day() -> None:
    m = HeaterMeter(source="sensor.prise_puissance")
    start = _midnight(0)
    m.set_power(start, 500)
    for i in range(1, 8 * 60 + 1):
        m.tick(start + timedelta(minutes=i), None)
    s = m.summary(start + timedelta(hours=8), 0.2)
    assert s["estimate"] and abs(s["per_day_kwh"] - 12.0) < 0.1


def test_changing_plug_keeps_days_but_not_counter() -> None:
    m = HeaterMeter(source="sensor.a")
    m.add_counter(_midnight(0) + timedelta(hours=1), 50.0)
    m.days["2026-01-01"] = [3.0, 0.0, 0]
    n = HeaterMeter(m.as_dict(), source="sensor.b")
    assert n.counter is None and "2026-01-01" in n.days


async def test_cost_sensors_created(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.eau", "33.4", {"unit_of_measurement": "°C",
                                                 "device_class": "temperature"})
    hass.states.async_set("sensor.ext", "8", {"unit_of_measurement": "°C",
                                              "device_class": "temperature"})
    hass.states.async_set("sensor.prise", "1.0", {"unit_of_measurement": "kWh",
                                                  "device_class": "energy"})
    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id="sensor.eau",
                            data={CONF_WATER: "sensor.eau", CONF_OUTDOOR: "sensor.ext",
                                  CONF_POWER: "sensor.prise", CONF_PRICE: 0.25})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set("sensor.prise", "1.8", {"unit_of_measurement": "kWh",
                                                  "device_class": "energy"})
    await hass.async_block_till_done()
    coord = entry.runtime_data
    coord.async_set_updated_data(coord.compute())
    await hass.async_block_till_done()
    reg = er.async_get(hass)

    def state(key: str):
        return hass.states.get(reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}"))

    assert abs(float(state("energie_maintien_jour").state) - 0.8) < 1e-6
    assert abs(float(state("cout_maintien_jour").state) - 0.2) < 1e-6
    assert state("cout_maintien_jour").attributes["unit_of_measurement"] == hass.config.currency
    assert state("cout_maintien_moyen") is not None
    assert "cout_maintien_moyen" in state("etat").attributes["entites"]


async def test_card_finds_plug_power_next_to_energy(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.eau", "33.4", {"unit_of_measurement": "°C",
                                                 "device_class": "temperature"})
    plug_entry = MockConfigEntry(domain="shelly")
    plug_entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=plug_entry.entry_id,
                                                 identifiers={("shelly", "plug")})
    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "shelly", "e", suggested_object_id="prise_energie",
                            device_id=dev.id, original_device_class="energy")
    reg.async_get_or_create("sensor", "shelly", "p", suggested_object_id="prise_puissance",
                            device_id=dev.id, original_device_class="power")
    hass.states.async_set("sensor.prise_energie", "1.0", {"unit_of_measurement": "kWh",
                                                          "device_class": "energy"})
    hass.states.async_set("sensor.prise_puissance", "2980", {"unit_of_measurement": "W",
                                                             "device_class": "power"})
    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id="sensor.eau",
                            data={CONF_WATER: "sensor.eau", CONF_POWER: "sensor.prise_energie"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.card_info()["puissance_prise"] == "sensor.prise_puissance"
