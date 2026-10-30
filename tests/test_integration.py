"""Installation de l'intégration dans un Home Assistant de test."""
from __future__ import annotations

from datetime import timedelta

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bain_nordique.const import CONF_OUTDOOR, CONF_WATER, CONF_WIND, DOMAIN

WATER = "sensor.eau"
WEATHER = "weather.maison"


def _states(hass: HomeAssistant, water: float = 33.4) -> None:
    hass.states.async_set(WATER, str(water), {"unit_of_measurement": "°C",
                                              "device_class": "temperature"})
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8.0, "temperature_unit": "°C",
                                              "wind_speed": 5.0, "wind_speed_unit": "m/s"})


async def test_config_flow(hass: HomeAssistant) -> None:
    _states(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WATER: WATER, CONF_OUTDOOR: WEATHER, CONF_WIND: WEATHER})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WATER] == WATER


async def test_setup_and_predict(hass: HomeAssistant) -> None:
    _states(hass)
    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id=WATER,
                            data={CONF_WATER: WATER, CONF_OUTDOOR: WEATHER, CONF_WIND: WEATHER})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coord = entry.runtime_data
    assert coord.wind and abs(coord._wind_now() - 18.0) < 0.01      # 5 m/s → 18 km/h
    reg = er.async_get(hass)

    def eid(platform: str, key: str) -> str:
        return reg.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")

    assert hass.states.get(eid("sensor", "heure_cible")).state not in ("unknown", "unavailable")
    assert float(hass.states.get(eid("sensor", "pic_prevu")).state) > 36
    assert hass.states.get(eid("sensor", "etat")).state is not None
    coord.async_set_updated_data(coord.compute())        # toutes les plateformes sont en place
    await hass.async_block_till_done()
    info = hass.states.get(eid("sensor", "etat")).attributes
    assert info["integration"] == DOMAIN and info["sonde_eau"] == WATER
    assert info["entites"]["cible"] == eid("number", "cible")
    assert info["entites"]["feu_allume"] == eid("button", "feu_allume")

    # la sonde chauffe : 2,5 °C/h pendant 1 h
    now = dt_util.utcnow()
    events = []
    hass.bus.async_listen(f"{DOMAIN}_event", lambda e: events.append(e.data["type"]))
    for i in range(1, 61):
        coord.engine.feed(now - timedelta(minutes=61 - i), 33.4 + 2.5 * i / 60)
    assert coord.engine.fire is not None

    await hass.services.async_call("button", "press", {"entity_id": eid("button", "feu_allume")},
                                   blocking=True)
    await hass.async_block_till_done()
    assert "late_declaration" in events
    await hass.services.async_call("number", "set_value",
                                   {"entity_id": eid("number", "cible"), "value": 39},
                                   blocking=True)
    assert coord.target == 39
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert hass.states.get(eid("binary_sensor", "feu_en_cours")).state == "on"
    assert int(hass.states.get(eid("sensor", "intensite_feu")).state) > 0
    assert float(hass.states.get(eid("sensor", "temperature_exterieure")).state) == 8.0
    assert float(hass.states.get(eid("sensor", "vent")).state) == 18.0   # 5 m/s
    for key in ("conseil", "nombre_feux", "coef_pertes", "sensibilite_vent"):
        assert hass.states.get(eid("sensor", key)) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_migrate_v1(hass: HomeAssistant) -> None:
    _states(hass)
    entry = MockConfigEntry(domain=DOMAIN, version=1, unique_id=WATER,
                            data={CONF_WATER: WATER, CONF_OUTDOOR: WEATHER})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2


async def test_options_change_water_probe(hass: HomeAssistant) -> None:
    _states(hass)
    hass.states.async_set("sensor.eau2", "33.5", {"unit_of_measurement": "°C",
                                                  "device_class": "temperature"})
    entry = MockConfigEntry(domain=DOMAIN, version=2, unique_id=WATER,
                            data={CONF_WATER: WATER, CONF_OUTDOOR: WEATHER})
    entry.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, version=2, unique_id="sensor.autre",
                            data={CONF_WATER: "sensor.autre", CONF_OUTDOOR: WEATHER})
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_WATER in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WATER: "sensor.autre", CONF_OUTDOOR: WEATHER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_WATER: "already_configured"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WATER: "sensor.eau2", CONF_OUTDOOR: WEATHER})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.unique_id == "sensor.eau2"
    assert entry.runtime_data.water == "sensor.eau2"
