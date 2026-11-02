"""Consommation du maintien électrique, mesurée par une prise (compteur kWh ou puissance W)."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

KEEP_DAYS = 90
MAX_GAP = timedelta(hours=1)        # au-delà, une puissance n'est plus intégrée (coupure)
MIN_ESTIMATE = timedelta(hours=6)   # durée suivie avant d'extrapoler la journée en cours


def _day(ts: datetime) -> str:
    return dt_util.as_local(ts).date().isoformat()


class HeaterMeter:
    """Énergie consommée par jour (date locale), avec la température extérieure moyenne.

    Un compteur d'énergie (kWh, Wh…) est lu par différence ; une puissance (W, kW)
    est intégrée dans le temps. Une coupure de plus d'une heure n'est pas comptée."""

    def __init__(self, data: dict | None = None, source: str | None = None) -> None:
        data = data or {}
        same = data.get("source") == source
        self.source = source
        self.days: dict[str, list[float]] = data.get("days", {})   # date → [kWh, Σ ext, n ext]
        self.since: str | None = data.get("since") if same else None
        self.counter: float | None = data.get("counter") if same else None
        self._watts: float | None = None
        self._watts_ts: datetime | None = None

    def as_dict(self) -> dict:
        return {"source": self.source, "days": self.days, "since": self.since,
                "counter": self.counter}

    def _bucket(self, ts: datetime) -> list[float]:
        return self.days.setdefault(_day(ts), [0.0, 0.0, 0])

    def _start(self, ts: datetime) -> None:
        if self.since is None:
            self.since = ts.isoformat()

    def add_counter(self, ts: datetime, kwh_total: float) -> None:
        self._start(ts)
        if self.counter is not None:
            delta = kwh_total - self.counter
            if delta < 0:                       # compteur remis à zéro (redémarrage de la prise)
                delta = kwh_total
            self._bucket(ts)[0] += delta
        self.counter = kwh_total

    def set_power(self, ts: datetime, watts: float) -> None:
        self._integrate(ts)
        self._start(ts)
        self._watts, self._watts_ts = watts, ts

    def _integrate(self, ts: datetime) -> None:
        if self._watts is None or self._watts_ts is None:
            return
        dt = ts - self._watts_ts
        if timedelta(0) < dt <= MAX_GAP:
            self._bucket(ts)[0] += self._watts * dt.total_seconds() / 3.6e6
        if dt > timedelta(0):
            self._watts_ts = ts

    def tick(self, ts: datetime, te: float | None) -> None:
        """Appelé chaque minute : intègre la puissance, note la température extérieure."""
        self._integrate(ts)
        if self.since is not None and te is not None:
            b = self._bucket(ts)
            b[1] += te
            b[2] += 1
        cutoff = _day(ts - timedelta(days=KEEP_DAYS))
        for d in [d for d in self.days if d < cutoff]:
            del self.days[d]

    def summary(self, now: datetime, price: float) -> dict:
        today = _day(now)
        b = self.days.get(today, [0.0, 0.0, 0])
        out: dict = {"kwh_today": round(b[0], 3), "cost_today": round(b[0] * price, 2),
                     "per_day_kwh": None, "per_day_cost": None, "estimate": False, "days": []}
        if self.since is None:
            return out
        since = dt_util.parse_datetime(self.since)
        first = _day(since)
        complete = sorted(d for d in self.days if first < d < today)
        for d in complete[-30:]:
            kwh, s, n = self.days[d]
            out["days"].append({"date": d, "kwh": round(kwh, 2), "cout": round(kwh * price, 2),
                                "ext": round(s / n, 1) if n else None})
        last7 = complete[-7:]
        if last7:
            kwh = sum(self.days[d][0] for d in last7) / len(last7)
        else:                                   # pas encore de journée complète : on extrapole
            start = max(since, dt_util.start_of_local_day(now))
            if now - start < MIN_ESTIMATE:
                return out
            kwh = b[0] * timedelta(days=1) / (now - start)
            out["estimate"] = True
        out["per_day_kwh"] = round(kwh, 2)
        out["per_day_cost"] = round(kwh * price, 2)
        out["days_counted"] = len(last7)
        return out
