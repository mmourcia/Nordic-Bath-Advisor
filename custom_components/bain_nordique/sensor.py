"""Capteurs : état, prévisions, statistiques, paramètres appris."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfSpeed, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BainCoordinator
from .entity import BainEntity

STATES = ["hold", "cooling", "lit", "fire", "probe_out"]


@dataclass(frozen=True, kw_only=True)
class BainSensorDescription(SensorEntityDescription):
    value_fn: Callable[[BainCoordinator], Any]
    attr_fn: Callable[[BainCoordinator], dict] | None = None


def _iso(v):
    return v.isoformat() if v else None


def _pred(c: BainCoordinator) -> dict:
    return c.data.get("pred") or {}


def _stats(c: BainCoordinator) -> dict:
    return c.data.get("stats") or {}


def _mean_time(c: BainCoordinator, g: float | None) -> tuple[int | None, int]:
    g = c.target if g is None else g
    return _stats(c).get("mean_time", {}).get(g, (None, 0))


def _mean_time_desc(key: str, g: float | None) -> BainSensorDescription:
    return BainSensorDescription(
        key=key, icon="mdi:timer-outline", device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES, suggested_display_precision=0,
        value_fn=lambda c: _mean_time(c, g)[0],
        attr_fn=lambda c: {"cible": c.target if g is None else g, "feux": _mean_time(c, g)[1],
                           "depuis": "allumage (déclaré ou estimé), départ depuis le maintien"},
    )


def _k_attrs(c: BainCoordinator) -> dict:
    p = c.params
    k0, kw = p.k_fit()
    k = p.k(c.data.get("wind"))
    return {"k0": round(k0, 5), "k_vent_par_kmh": round(kw, 6), "fenetres_apprises": p.n_k,
            "constante_de_temps_h": round(1 / k), "derniere_mesure": c.engine.last_k}


SENSORS: tuple[BainSensorDescription, ...] = (
    BainSensorDescription(
        key="etat", icon="mdi:hot-tub", device_class=SensorDeviceClass.ENUM, options=STATES,
        value_fn=lambda c: c.data.get("state"),
        attr_fn=lambda c: c.card_info(),
    ),
    BainSensorDescription(
        key="conseil", icon="mdi:message-text-outline",
        value_fn=lambda c: c.data.get("advice"),
    ),
    BainSensorDescription(
        key="heure_cible", icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: _pred(c).get("target_time"),
        attr_fn=lambda c: {
            "cible": c.target,
            "si_feu_maintenant": _pred(c).get("if_now"),
            "au_plus_tot": _iso(_pred(c).get("target_earliest")),
            "au_plus_tard": _iso(_pred(c).get("target_latest")),
            "passages": _pred(c).get("crossings"),
            "trajectoire": _pred(c).get("trajectory")},
    ),
    BainSensorDescription(
        key="duree_avant_cible", icon="mdi:timer-sand",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda c: _pred(c).get("target_min"),
        attr_fn=lambda c: {"si_feu_maintenant": _pred(c).get("if_now")},
    ),
    BainSensorDescription(
        key="pic_prevu", icon="mdi:thermometer-high",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1,
        value_fn=lambda c: _pred(c).get("peak"),
        attr_fn=lambda c: {"heure": _iso(_pred(c).get("peak_time")),
                           "fourchette_basse": _pred(c).get("peak_low"),
                           "fourchette_haute": _pred(c).get("peak_high"),
                           "si_feu_maintenant": _pred(c).get("if_now")},
    ),
    BainSensorDescription(
        key="heure_pic", icon="mdi:clock-star-four-points-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: _pred(c).get("peak_time"),
    ),
    BainSensorDescription(
        key="intensite_feu", icon="mdi:fire", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        value_fn=lambda c: round(_pred(c)["intensity"] * 100) if _pred(c).get("intensity") else None,
    ),
    BainSensorDescription(
        key="sous_la_cible", icon="mdi:thermometer-chevron-down",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.data.get("below_target"),
    ),
    BainSensorDescription(
        key="nombre_feux", icon="mdi:counter", state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: _stats(c).get("count"),
        attr_fn=lambda c: {"par_mois": _stats(c).get("by_month"),
                           "baignades_detectees": _stats(c).get("baths")},
    ),
    BainSensorDescription(
        key="feux_30_jours", icon="mdi:calendar-month", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _stats(c).get("count_30d"),
    ),
    _mean_time_desc("temps_moyen_38", 38.0),
    _mean_time_desc("temps_moyen_39", 39.0),
    _mean_time_desc("temps_moyen_cible", None),
    BainSensorDescription(
        key="montee_moyenne", icon="mdi:trending-up", native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda c: _stats(c).get("mean_rate"),
        attr_fn=lambda c: {"pic_moyen": _stats(c).get("mean_peak")},
    ),
    BainSensorDescription(
        key="dernier_feu", icon="mdi:fire-circle",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1,
        value_fn=lambda c: (_stats(c).get("last") or {}).get("pic"),
        attr_fn=lambda c: _stats(c).get("last") or {},
    ),
    BainSensorDescription(
        key="pertes_actuelles", icon="mdi:heat-wave", native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
        value_fn=lambda c: c.data.get("losses"),
        attr_fn=lambda c: {"temperature_exterieure": c.data.get("te"),
                           "vent_kmh": c.data.get("wind")},
    ),
    BainSensorDescription(
        key="coef_pertes", icon="mdi:heat-wave", native_unit_of_measurement="1/h",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: round(c.params.k(c.data.get("wind")), 5),
        attr_fn=_k_attrs,
    ),
    BainSensorDescription(
        key="consigne_maintien", icon="mdi:thermostat",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (round((c.params.hold_low + c.params.hold_high) / 2, 2)
                            if c.params.hold_low is not None else None),
        attr_fn=lambda c: {"bas": c.params.hold_low, "haut": c.params.hold_high,
                           "vu_le": c.params.hold_seen, "plateaux_appris": c.params.n_hold},
    ),
    BainSensorDescription(
        key="delai_allumage", icon="mdi:timer-play-outline",
        device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: round(c.params.lag_h * 60),
        attr_fn=lambda c: {"delais_appris": c.params.n_lag},
    ),
    BainSensorDescription(
        key="courbe_feu", icon="mdi:chart-bell-curve", native_unit_of_measurement="°C",
        suggested_display_precision=1, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: round(c.params.heat_until(8.0), 1),
        attr_fn=lambda c: {"feux_appris": c.params.n_curve, "pas_min": 5,
                           "apport_c_par_h": c.params.curve},
    ),
)

OUTDOOR_SENSOR = BainSensorDescription(
    key="temperature_exterieure", icon="mdi:thermometer",
    device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1,
    value_fn=lambda c: round(c.data["te"], 2) if c.data.get("te") is not None else None,
    attr_fn=lambda c: {"source": c.outdoor},
)

WIND_SPEED_SENSOR = BainSensorDescription(
    key="vent", icon="mdi:weather-windy",
    device_class=SensorDeviceClass.WIND_SPEED, state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR, suggested_display_precision=0,
    value_fn=lambda c: round(c.data["wind"], 1) if c.data.get("wind") is not None else None,
    attr_fn=lambda c: {"source": c.wind},
)

WIND_SENSOR = BainSensorDescription(
    key="sensibilite_vent", icon="mdi:weather-windy", native_unit_of_measurement="%",
    suggested_display_precision=0, entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda c: (round(c.params.k_fit()[1] * 10 / c.params.k_fit()[0] * 100)
                        if c.params.n_k else None),
    attr_fn=lambda c: {"signification": "pertes en plus par tranche de 10 km/h de vent"},
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coord: BainCoordinator = entry.runtime_data
    descs = list(SENSORS) + [OUTDOOR_SENSOR]
    descs += [WIND_SPEED_SENSOR, WIND_SENSOR] if coord.wind else []
    async_add_entities(BainSensor(coord, d) for d in descs)


class BainSensor(BainEntity, SensorEntity):
    entity_description: BainSensorDescription

    def __init__(self, coordinator: BainCoordinator, description: BainSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict | None:
        fn = self.entity_description.attr_fn
        return fn(self.coordinator) if fn else None
