"""Coordinateur : écoute les sondes, fait tourner le moteur, publie prévisions et stats."""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STARTED,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import CoreState, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import SpeedConverter, TemperatureConverter

from .const import (
    BOOTSTRAP_DAYS,
    CONF_OUTDOOR,
    CONF_WATER,
    CONF_WIND,
    DEFAULT_TARGET,
    DOMAIN,
    EVENT,
    RESUME_OVERLAP,
    SHOWN_TARGETS,
    STAT_TARGETS,
)
from .model import Engine, Params

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
SPREAD = 0.2                     # fourchette : feu 20 % moins / plus généreux
LIVE_EVENTS = {"fire_start", "fire_end", "fire_discarded", "fire_failed", "opened",
               "probe_out", "probe_back", "hold_learned"}


# ---------------------------------------------------------------- lecture des entités
def read_temperature(state: State | None) -> float | None:
    """°C depuis un capteur de température ou une entité météo."""
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        if state.domain == "weather":
            value = float(state.attributes["temperature"])
            unit = state.attributes.get("temperature_unit", UnitOfTemperature.CELSIUS)
        else:
            value = float(state.state)
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS)
    except (KeyError, TypeError, ValueError):
        return None
    if unit != UnitOfTemperature.CELSIUS:
        try:
            value = TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        except Exception:  # noqa: BLE001 - unité inconnue : on garde la valeur
            pass
    return value


def read_wind(state: State | None) -> float | None:
    """km/h depuis un capteur de vent ou une entité météo."""
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        if state.domain == "weather":
            value = float(state.attributes["wind_speed"])
            unit = state.attributes.get("wind_speed_unit", UnitOfSpeed.KILOMETERS_PER_HOUR)
        else:
            value = float(state.state)
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfSpeed.KILOMETERS_PER_HOUR)
    except (KeyError, TypeError, ValueError):
        return None
    if unit != UnitOfSpeed.KILOMETERS_PER_HOUR:
        try:
            value = SpeedConverter.convert(value, unit, UnitOfSpeed.KILOMETERS_PER_HOUR)
        except Exception:  # noqa: BLE001
            pass
    return value


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


class BainCoordinator(DataUpdateCoordinator[dict]):
    """Recalcule chaque minute et à chaque nouveau relevé."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(minutes=1))
        self.entry = entry
        conf = {**entry.data, **entry.options}
        self.water: str = conf[CONF_WATER]
        self.outdoor: str | None = conf.get(CONF_OUTDOOR)
        self.wind: str | None = conf.get(CONF_WIND)
        self.params = Params()
        self.engine = Engine(self.params, [], use_wind=bool(self.wind))
        self.target: float = DEFAULT_TARGET
        self.replaying = False
        self._queue: list[tuple[datetime, str, float]] = []
        self._notified: set[str] = set()
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._bootstrapped = False

    # ------------------------------------------------------------ persistance
    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self.params = Params.from_dict(stored.get("params", {}))
        self.engine = Engine(self.params, stored.get("fires", []), use_wind=bool(self.wind))
        self.engine.last_k = stored.get("last_k")
        self.target = stored.get("target", DEFAULT_TARGET)
        self._bootstrapped = stored.get("bootstrapped", False)
        last_ts = stored.get("last_ts")
        self.engine.set_outdoor(self._outdoor_now())
        self.engine.set_wind(self._wind_now())

        ids = [self.water] + [e for e in (self.outdoor, self.wind) if e]
        self.entry.async_on_unload(async_track_state_change_event(self.hass, ids, self._on_state))

        resume = dt_util.parse_datetime(last_ts) if last_ts else None
        declared = dt_util.parse_datetime(stored["declared"]) if stored.get("declared") else None

        async def _start(_event=None) -> None:
            await self._async_replay(resume, declared)

        if self.hass.state is CoreState.running:
            self.entry.async_create_background_task(self.hass, _start(), f"{DOMAIN}_replay")
        else:
            self.entry.async_on_unload(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start))

    def _snapshot(self) -> dict:
        e = self.engine
        return {"params": self.params.as_dict(), "fires": e.fires[-500:], "last_k": e.last_k,
                "target": self.target, "bootstrapped": self._bootstrapped,
                "last_ts": e.last_ts.isoformat() if e.last_ts else None,
                "declared": e.declared.isoformat() if e.declared else None}

    def _save_later(self) -> None:
        self._store.async_delay_save(self._snapshot, 30)

    async def async_shutdown_save(self) -> None:
        await self._store.async_save(self._snapshot())

    # ------------------------------------------------------------ historique
    async def _async_history(self, start: datetime, end: datetime) -> dict[str, list[State]]:
        from homeassistant.components.recorder import get_instance, history

        ids = [self.water] + [e for e in (self.outdoor, self.wind) if e]
        return await get_instance(self.hass).async_add_executor_job(
            lambda: history.get_significant_states(
                self.hass, start, end, entity_ids=ids, significant_changes_only=False,
                minimal_response=False, no_attributes=False, include_start_time_state=True))

    async def _async_replay(self, resume: datetime | None, declared: datetime | None,
                            full: bool = False) -> None:
        """Relit l'historique du recorder.

        Première installation (ou « Réapprendre ») : 60 jours, avec apprentissage.
        Redémarrage : les 14 dernières heures, sans réapprendre ce qui l'a déjà été,
        pour reprendre un feu en cours et combler la coupure."""
        now = dt_util.utcnow()
        if full or not self._bootstrapped:
            start, quiet = now - timedelta(days=BOOTSTRAP_DAYS), None
        elif resume:
            start, quiet = resume - RESUME_OVERLAP, resume
        else:
            return
        self.replaying = True
        try:
            states = await self._async_history(start, now)
        except Exception as err:  # noqa: BLE001 - recorder absent ou indisponible
            _LOGGER.warning("Historique indisponible, apprentissage en direct seulement : %s", err)
            states = {}
        stream: list[tuple[datetime, str, float]] = []
        for eid, kind, reader in ((self.water, "w", read_temperature),
                                  (self.outdoor, "o", read_temperature),
                                  (self.wind, "v", read_wind)):
            for st in states.get(eid, []) if eid else []:
                value = reader(st)
                if value is not None:
                    stream.append((st.last_updated, kind, value))
        stream.sort(key=lambda x: (x[0], x[1] == "w"))
        params = copy.deepcopy(self.params) if quiet else Params()
        if quiet:
            fires = list(self.engine.fires)
        else:                    # on garde les feux plus anciens que l'historique disponible
            first = stream[0][0].isoformat() if stream else now.isoformat()
            fires = [f for f in self.engine.fires if f["debut_montee"] < first]
        engine = Engine(params, fires, use_wind=bool(self.wind))
        engine.last_k = self.engine.last_k
        engine.quiet_until = quiet
        n_fires = len(fires)
        await self.hass.async_add_executor_job(self._feed_all, engine, stream)
        engine.quiet_until = None
        if declared and now - declared < Engine.DECLARE_TTL and engine.fire is None:
            engine.declared = declared
        # relevés arrivés pendant la relecture
        queued, self._queue = self._queue, []
        self.params, self.engine = params, engine
        self.replaying = False
        self._bootstrapped = True
        engine.set_outdoor(self._outdoor_now())
        engine.set_wind(self._wind_now())
        self._feed_all(engine, queued)
        if engine.fire:                              # cibles déjà passées : pas de notification
            self._notified = {f"{engine.fire.rise_start.isoformat()}:{k}" for k in engine.fire.reached}
        _LOGGER.info("Bain nordique : %d relevés relus depuis %s, %d feu(x) ajouté(s)",
                     len(stream), start.isoformat(), len(engine.fires) - n_fires)
        await self._store.async_save(self._snapshot())
        self.async_set_updated_data(self.compute())

    @staticmethod
    def _feed_all(engine: Engine, stream: list[tuple[datetime, str, float]]) -> None:
        for ts, kind, value in stream:
            if kind == "o":
                engine.set_outdoor(value)
            elif kind == "v":
                engine.set_wind(value)
            else:
                engine.feed(ts, value)

    async def async_relearn(self) -> None:
        self._fire("relearn_started")
        await self._async_replay(None, None, full=True)

    # ------------------------------------------------------------ direct
    def _outdoor_now(self) -> float | None:
        return read_temperature(self.hass.states.get(self.outdoor)) if self.outdoor else None

    def _wind_now(self) -> float | None:
        return read_wind(self.hass.states.get(self.wind)) if self.wind else None

    def _water_now(self) -> float | None:
        return read_temperature(self.hass.states.get(self.water))

    def _fire(self, kind: str, **data) -> None:
        self.hass.bus.async_fire(EVENT, {"type": kind, **data})

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None:
            return
        eid = event.data["entity_id"]
        if eid == self.water:
            kind, value = "w", read_temperature(new)
        elif eid == self.outdoor:
            kind, value = "o", read_temperature(new)
        else:
            kind, value = "v", read_wind(new)
        if value is None:
            return
        if self.replaying:
            self._queue.append((new.last_updated, kind, value))
            return
        if kind == "o":
            self.engine.set_outdoor(value)
            return
        if kind == "v":
            self.engine.set_wind(value)
            return
        save = False
        for name, data in self.engine.feed(new.last_updated, value):
            if name in LIVE_EVENTS:
                self._fire(name, **data)
            if name in ("fire_end", "k_learned", "hold_learned", "fire_start"):
                save = True
        self._check_target()
        if save:
            self._save_later()
        self.async_set_updated_data(self.compute())

    def _check_target(self) -> None:
        f = self.engine.fire
        if not f:
            return
        key = f"{self.target:.1f}"
        tag = f"{f.rise_start.isoformat()}:{key}"
        if key in f.reached and tag not in self._notified:
            self._notified.add(tag)
            self._fire("target_reached", cible=self.target, eau=self._water_now())

    # ------------------------------------------------------------ actions
    @callback
    def declare_fire(self) -> None:
        kind = self.engine.declare(dt_util.utcnow())
        self._fire("ignition" if kind == "declared" else "late_declaration")
        self._save_later()
        self.async_set_updated_data(self.compute())

    @callback
    def cancel_fire(self) -> None:
        self.engine.cancel()
        self._fire("fire_cancelled")
        self._save_later()
        self.async_set_updated_data(self.compute())

    @callback
    def set_target(self, value: float) -> None:
        self.target = value
        self._save_later()
        self.async_set_updated_data(self.compute())

    async def _async_update_data(self) -> dict:
        return self.compute()

    def card_info(self) -> dict:
        """Ce dont la carte Lovelace a besoin pour se configurer seule."""
        from homeassistant.helpers import entity_registry as er

        prefix = f"{self.entry.entry_id}_"
        ents = {e.unique_id.removeprefix(prefix): e.entity_id
                for e in er.async_entries_for_config_entry(er.async_get(self.hass), self.entry.entry_id)
                if e.unique_id.startswith(prefix)}
        p = self.params
        return {"integration": DOMAIN, "entites": ents, "sonde_eau": self.water,
                "exterieur": self.outdoor, "temperature_eau": self.data.get("tw") if self.data else None,
                "temperature_exterieure": self.data.get("te") if self.data else None,
                "vent_kmh": round(self.data["wind"], 1) if self.data and self.data.get("wind") is not None else None,
                "maintien_bas": p.hold_low, "maintien_haut": p.hold_high}

    # ------------------------------------------------------------ calcul
    def compute(self) -> dict:
        now = dt_util.utcnow()
        e, p = self.engine, self.params
        tw, te, wind = self._water_now(), self._outdoor_now(), self._wind_now()
        if te is None:
            te = e.te
        fire = e.fire
        d: dict = {"tw": tw, "te": te, "wind": wind, "target": self.target,
                   "in_fire": fire is not None, "probe_out": e.probe_out is not None,
                   "declared": e.declared is not None, "replaying": self.replaying,
                   "stats": self._stats(now)}
        floor = p.floor(now)
        if e.probe_out:
            d["state"] = "probe_out"
        elif fire:
            d["state"] = "fire"
        elif e.declared:
            d["state"] = "lit"
        elif floor is not None and tw is not None and tw <= (p.hold_high or floor) + 0.3:
            d["state"] = "hold"
        elif tw is not None:
            d["state"] = "cooling"
        else:
            d["state"] = None
        d["ready"] = bool(tw is not None and not e.probe_out and tw >= self.target - 0.05)
        d["losses"] = round(p.k(wind) * (tw - te), 2) if tw is not None and te is not None else None

        if tw is None or te is None or e.probe_out:
            d.update(pred=None, advice=self._advice(d, now))
            return d

        targets = sorted(set(SHOWN_TARGETS + [self.target]))
        r = e.predict(now, tw, te, wind, targets, traj_every=5)
        lo = e.predict(now, tw, te, wind, [self.target], a_mult=1 - SPREAD)
        hi = e.predict(now, tw, te, wind, [self.target], a_mult=1 + SPREAD)
        at = lambda h: now + timedelta(hours=h) if h is not None else None
        c = r["cross"].get(self.target)
        d["pred"] = {
            "if_now": fire is None,
            "target_time": at(c),
            "target_min": None if c is None else max(0, round(c * 60)),
            "target_earliest": at(hi["cross"].get(self.target)),
            "target_latest": at(lo["cross"].get(self.target)),
            "peak": round(r["peak"], 1), "peak_time": at(r["peak_h"]),
            "peak_low": round(lo["peak"], 1), "peak_high": round(hi["peak"], 1),
            "crossings": {f"{g:g}": at(h).isoformat() if h is not None else None
                          for g, h in r["cross"].items()},
            "trajectory": [(at(t).isoformat(), round(v, 2)) for t, v in r["traj"]],
            "intensity": e.intensity(now) if fire else None,
        }
        d["below_target"] = None
        if not fire and tw >= self.target:
            h = e.cooling(now, tw, te, wind, self.target)
            d["below_target"] = at(h)
        d["advice"] = self._advice(d, now)
        return d

    def _stats(self, now: datetime) -> dict:
        fires = self.engine.fires
        p = self.params
        start_max = (p.hold_high + 0.5) if p.hold_high is not None else None

        def mean_time(g: float) -> tuple[float | None, int]:
            key = f"{g:.1f}"
            pool = [f for f in fires if key in f.get("atteint", {}) and f["de"] <= g - 3]
            if start_max is not None:
                warm = [f for f in pool if f["de"] <= start_max]
                pool = warm or pool
            pool = pool[-10:]
            vals = [f["atteint"][key] for f in pool]
            return (round(sum(vals) / len(vals)) if vals else None), len(vals)

        month: dict[str, int] = {}
        for f in fires:
            m = f["allumage"][:7]
            month[m] = month.get(m, 0) + 1
        recent = [f for f in fires
                  if now - dt_util.parse_datetime(f["allumage"]) <= timedelta(days=30)]
        times = {g: mean_time(g) for g in set(STAT_TARGETS) | {self.target}}
        rates = [f["montee_c_h"] for f in fires[-10:] if f.get("montee_c_h")]
        return {
            "count": len(fires), "count_30d": len(recent), "by_month": month,
            "baths": sum(1 for f in fires if f.get("baignade")),
            "mean_time": times,
            "mean_rate": _mean(rates),
            "mean_peak": _mean([f["pic"] for f in fires[-10:]]),
            "last": fires[-1] if fires else None,
        }

    def _advice(self, d: dict, now: datetime) -> str:
        def hm(t: datetime | None) -> str:
            return dt_util.as_local(t).strftime("%Hh%M") if t else "?"

        def num(x: float) -> str:
            return f"{round(x, 1):g}".replace(".", ",")

        tg = num(self.target)
        if d["replaying"]:
            return "Lecture de l'historique…"
        if d["probe_out"]:
            return "Sonde hors de l'eau ?"
        pr = d.get("pred")
        if d["tw"] is None or not pr:
            return "Sondes indisponibles"
        eau = f"{num(d['tw'])} °C"
        if d["in_fire"]:
            if d["ready"]:
                return f"✅ {eau} — pic {num(pr['peak'])} °C vers {hm(pr['peak_time'])}"
            if pr["target_time"]:
                return (f"🔥 {eau} — {tg} °C vers {hm(pr['target_time'])}, "
                        f"pic {num(pr['peak'])} °C vers {hm(pr['peak_time'])}")
            return f"🔥 {eau} — pic {num(pr['peak'])} °C vers {hm(pr['peak_time'])} ({tg} °C hors de portée)"
        if d["ready"]:
            below = d.get("below_target")
            return f"✅ {eau} — au-dessus de {tg} °C jusqu'à {hm(below)}" if below else f"✅ {eau}"
        if pr["target_time"]:
            return (f"{eau} · feu maintenant → {tg} °C vers {hm(pr['target_time'])} "
                    f"(pic {num(pr['peak'])} °C vers {hm(pr['peak_time'])})")
        return f"{eau} · feu maintenant → pic {num(pr['peak'])} °C vers {hm(pr['peak_time'])}"
