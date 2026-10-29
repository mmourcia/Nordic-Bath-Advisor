"""Modèle thermique du bain nordique et apprentissage — Python pur, sans HA.

Bilan : dT/dt = P(τ) − k(vent)·(T − T_ext), avec un plancher à la consigne
du maintien électrique quand il est actif.

* P(τ) est la « courbe du feu » : apport de chaleur (°C d'eau par heure) en
  fonction du temps τ écoulé depuis le début de la montée. Elle est apprise
  feu après feu, sans hypothèse de forme (moyenne pondérée par pas de 5 min).
* k = k0 + kw·vent est appris sur les refroidissements sans feu, au-dessus de
  la consigne (régression linéaire avec oubli progressif).
* La consigne du maintien est apprise sur les plateaux de plusieurs heures.

Le moteur reçoit les relevés dans l'ordre (en direct ou en rejouant
l'historique) et renvoie des événements ; il ne dépend pas de Home Assistant,
ce qui permet de le tester sur un export CSV (voir tools/replay_csv.py).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

BIN_MIN = 5                       # pas de la courbe du feu (min)
BIN_H = BIN_MIN / 60
CURVE_BINS = 96                   # 8 h
CURVE_W_MAX = 4.0                 # poids max d'un pas : le dernier feu compte pour ≥ 20 %
GRID = [x / 2 for x in range(66, 91)]   # 33,0 … 45,0 °C : heures de passage mémorisées
SIM_STEP_H = 2 / 60
FIT_SIGMA = 0.3                   # °C : bruit sur la chaleur reçue (sonde, stratification)
FIT_PRIOR_A = 0.15                # dispersion (log) de la chaleur d'un feu à l'autre
FIT_PRIOR_S = 0.5                 # … et de sa durée (un feu lent chauffe autant, plus longtemps)

# Courbe par défaut apprise sur les feux d'octobre 2026 (feu inversé standard).
DEFAULT_CURVE = [
    3.1, 3.2, 3.3, 3.6, 3.9, 4.0, 4.0, 3.9, 3.7, 3.5, 3.2, 3.0,
    2.7, 2.5, 2.2, 2.0, 1.8, 1.7, 1.7, 1.6, 1.5, 1.4, 1.2, 1.0,
    0.8, 0.9, 0.8, 1.0, 1.2, 1.3, 1.2, 1.0, 0.8, 0.7, 0.7, 0.6,
    0.5, 0.4, 0.3, 0.2, 0.1, 0.1, 0.2, 0.2,
]


def _default_curve() -> list[float]:
    return DEFAULT_CURVE + [0.0] * (CURVE_BINS - len(DEFAULT_CURVE))


@dataclass
class Params:
    k_default: float = 0.014         # 1/h, utilisé tant que rien n'est appris
    lag_h: float = 0.3               # allumage → début de montée (h)
    n_lag: int = 0
    hold_low: float | None = None    # maintien électrique : bas / haut du cycle
    hold_high: float | None = None
    hold_seen: str | None = None     # dernier plateau reconnu (iso)
    n_hold: int = 0
    curve: list[float] = field(default_factory=_default_curve)
    curve_w: list[float] = field(default_factory=lambda: [1.0] * CURVE_BINS)
    n_curve: int = 0
    kstats: list[float] = field(default_factory=lambda: [0.0] * 5)   # sw, sx, sy, sxx, sxy
    n_k: int = 0

    KEYS = ("k_default", "lag_h", "n_lag", "hold_low", "hold_high", "hold_seen", "n_hold",
            "curve", "curve_w", "n_curve", "kstats", "n_k")

    def as_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.KEYS}

    @classmethod
    def from_dict(cls, data: dict) -> Params:
        p = cls()
        for key in cls.KEYS:
            if key in data:
                setattr(p, key, data[key])
        if len(p.curve) != CURVE_BINS:
            p.curve, p.curve_w = _default_curve(), [1.0] * CURVE_BINS
        return p

    # ------------------------------------------------------------ pertes
    K_FORGET = 0.98                  # oubli par fenêtre de 2 h : suit les saisons
    K_RIDGE = 400.0                  # (km/h)² : prudence sur l'effet du vent

    def k_fit(self) -> tuple[float, float]:
        """(k0, kw). Sans données : (k_default, 0)."""
        sw, sx, sy, sxx, sxy = self.kstats
        if sw < 1.0:
            return self.k_default, 0.0
        mx, my = sx / sw, sy / sw
        varx = sxx - sx * mx
        kw = (sxy - sx * my) / (varx + self.K_RIDGE * sw / 10) if varx > 1e-9 else 0.0
        kw = max(0.0, kw)            # le vent ne peut pas réduire les pertes
        return max(0.003, my - kw * mx), kw

    def mean_wind(self) -> float:
        sw, sx = self.kstats[0], self.kstats[1]
        return sx / sw if sw > 0 else 0.0

    def k(self, wind: float | None) -> float:
        k0, kw = self.k_fit()
        return k0 + kw * (self.mean_wind() if wind is None else wind)

    def add_k_obs(self, y: float, x: float, w: float) -> None:
        f = self.K_FORGET
        s = self.kstats
        self.kstats = [s[0] * f + w, s[1] * f + w * x, s[2] * f + w * y,
                       s[3] * f + w * x * x, s[4] * f + w * x * y]
        self.n_k += 1

    # ------------------------------------------------------------ maintien
    def floor(self, now: datetime) -> float | None:
        """Plancher du maintien électrique s'il a été vu ces 3 derniers jours."""
        if self.hold_low is None or not self.hold_seen:
            return None
        if now - datetime.fromisoformat(self.hold_seen) > timedelta(days=3):
            return None
        return self.hold_low

    # ------------------------------------------------------------ feu
    def p_at(self, tau_h: float) -> float:
        if tau_h < 0:
            return 0.0
        i = tau_h / BIN_H
        j = int(i)
        if j >= CURVE_BINS - 1:
            return 0.0
        a = i - j
        return self.curve[j] * (1 - a) + self.curve[j + 1] * a

    def heat_until(self, tau_h: float) -> float:
        """Chaleur (°C) apportée par un feu habituel entre 0 et τ."""
        full = int(max(tau_h, 0) / BIN_H)
        q = sum(self.curve[:min(full, CURVE_BINS)]) * BIN_H
        if full < CURVE_BINS:
            q += self.curve[full] * (max(tau_h, 0) - full * BIN_H)
        return q

    def curve_length_h(self) -> float:
        last = max((i for i, v in enumerate(self.curve) if v > 0.05), default=0)
        return (last + 1) * BIN_H

    def cum_heat(self) -> list[float]:
        """Chaleur cumulée de la courbe aux bornes des pas (pour heat_at)."""
        out, q = [0.0], 0.0
        for v in self.curve:
            q += v * BIN_H
            out.append(q)
        return out

    @staticmethod
    def heat_at(cum: list[float], tau_h: float) -> float:
        if tau_h <= 0:
            return 0.0
        i = tau_h / BIN_H
        j = int(i)
        if j >= CURVE_BINS:
            return cum[-1]
        return cum[j] + (cum[j + 1] - cum[j]) * (i - j)

    def fit_fire(self, pts: list[tuple[float, float]],
                 center: tuple[float, float] = (1.0, 1.0)) -> tuple[float, float]:
        """Ajuste (a, s) : ce feu = a × la chaleur du feu habituel, étirée dans le temps de s.

        pts = [(τ en h, chaleur reçue en °C)]. Moindres carrés avec un a priori
        centré sur les derniers feux (ln a ~ N(ln a0, σa²), ln s ~ N(ln s0, σs²)) : au
        début du feu on ne voit que la vitesse a/s, l'a priori départage chaleur et durée."""
        cum = self.cum_heat()
        la0, ls0 = math.log(center[0]), math.log(center[1])
        best, best_err = center, float("inf")
        for i in range(-10, 11):
            la = la0 + i * 0.1
            a = math.exp(la)
            for j in range(-10, 11):
                ls = ls0 + j * 0.1
                s = math.exp(ls)
                err = sum((q - a * self.heat_at(cum, t / s)) ** 2 for t, q in pts) / FIT_SIGMA ** 2
                err += ((la - la0) / FIT_PRIOR_A) ** 2 + ((ls - ls0) / FIT_PRIOR_S) ** 2
                if err < best_err:
                    best, best_err = (a, s), err
        return best

    def merge_curve(self, new: list[float | None]) -> None:
        """Ajoute un feu observé à la courbe du feu habituel (moyenne par pas)."""
        for i, v in enumerate(new[:CURVE_BINS]):
            if v is None:
                continue
            w = self.curve_w[i]
            self.curve[i] = round((self.curve[i] * w + v) / (w + 1), 3)
            self.curve_w[i] = min(w + 1, CURVE_W_MAX)
        self.n_curve += 1


@dataclass
class Sample:
    ts: datetime
    tw: float
    te: float | None
    wind: float | None


def slope(samples: list[Sample], min_span_h: float = 0.25) -> float | None:
    """Pente (°C/h) par régression linéaire."""
    if len(samples) < 2:
        return None
    t0 = samples[0].ts
    xs = [(s.ts - t0).total_seconds() / 3600 for s in samples]
    if xs[-1] < min_span_h:
        return None
    ys = [s.tw for s in samples]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def interp(samples: list[Sample], ts: datetime) -> float:
    """Température interpolée (relevés « au changement » : on tient la valeur)."""
    prev = samples[0]
    for s in samples:
        if s.ts >= ts:
            if s.ts == prev.ts:
                return s.tw
            a = (ts - prev.ts) / (s.ts - prev.ts)
            return prev.tw + (s.tw - prev.tw) * a
        prev = s
    return samples[-1].tw


def _h(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 3600


@dataclass
class Fire:
    rise_start: datetime
    base: float
    detected: datetime
    ignition: datetime | None = None   # déclarée par le bouton
    peak: float = 0.0
    peak_ts: datetime | None = None
    sig_peak: float = 0.0
    last_rise: datetime | None = None
    opened: datetime | None = None     # chute rapide (couverture ouverte, baignade)
    opened_rising: bool = False
    reached: dict = field(default_factory=dict)   # cible → heure de passage


class Engine:
    """Suit l'état du bain et apprend.

    États : repos (maintien ou refroidissement) → feu → repos. Un feu commence
    quand l'eau monte nettement (au-dessus du cycle du maintien électrique) et
    se termine 1 h après la dernière montée significative.
    """

    WINDOW = timedelta(minutes=30)
    BUFFER = timedelta(hours=14)
    RISE, RISE_COLD, RISE_DECLARED = 1.0, 1.5, 0.6    # °C/h
    END_AFTER = timedelta(minutes=60)
    OPEN = -1.0                                       # °C/h : chute = couverture ouverte
    PROBE_DROP = 3.0                                  # °C : sonde sortie de l'eau
    DECLARE_TTL = timedelta(hours=2)
    HOLD_SPAN = timedelta(hours=6)
    COOL_SPAN = timedelta(hours=2)

    def __init__(self, params: Params, fires: list[dict] | None = None,
                 use_wind: bool = False) -> None:
        self.p = params
        self.fires: list[dict] = fires if fires is not None else []
        self.use_wind = use_wind
        self.te: float | None = None
        self.wind: float | None = None
        self.buf: deque[Sample] = deque()
        self.fire: Fire | None = None
        self.declared: datetime | None = None
        self.probe_out: datetime | None = None
        self.last_good: Sample | None = None
        self.last_ts: datetime | None = None
        self.last_fire_end: datetime | None = None
        self.hold_win: list[Sample] = []
        self.cool_win: list[Sample] = []
        self.quiet_until: datetime | None = None    # rejeu : pas d'apprentissage avant
        self.last_k: dict | None = None
        self._fit_cache: tuple | None = None

    # ------------------------------------------------------------ entrées
    def set_outdoor(self, te: float | None) -> None:
        self.te = te

    def set_wind(self, wind: float | None) -> None:
        self.wind = wind

    def _learning(self, ts: datetime) -> bool:
        return self.quiet_until is None or ts > self.quiet_until

    def declare(self, ts: datetime) -> str:
        """Bouton « Feu allumé ». Retourne 'declared' ou 'late' (feu déjà détecté)."""
        if self.fire:            # déjà détecté : l'heure d'allumage reste estimée
            return "late"
        self.declared = ts
        return "declared"

    def cancel(self) -> None:
        """Bouton « Pas de feu » : oublie le feu en cours ou déclaré."""
        self.fire = None
        self.declared = None

    def reset_runtime(self) -> None:
        self.buf.clear()
        self.fire = None
        self.declared = None
        self.probe_out = None
        self.last_good = None
        self.hold_win, self.cool_win = [], []

    # ------------------------------------------------------------ relevés
    def feed(self, ts: datetime, tw: float) -> list[tuple[str, dict]]:
        if self.last_ts and ts <= self.last_ts:
            return []
        self.last_ts = ts
        ev: list[tuple[str, dict]] = []

        # sonde hors de l'eau : chute brutale, puis retour près de la dernière valeur
        if self.probe_out:
            back = self.last_good and tw >= self.last_good.tw - 2.0
            if not back and ts - self.probe_out < timedelta(hours=48):
                return ev
            ev.append(("probe_back", {"absence_min": round(_h(ts, self.probe_out) * 60)}))
            if not back:                                     # bain vidé / rempli
                self.reset_runtime()
            self.probe_out = None
            self.buf = deque(x for x in self.buf if x.ts > ts - self.WINDOW)
        elif (self.last_good and tw < self.last_good.tw - self.PROBE_DROP
              and ts - self.last_good.ts <= timedelta(minutes=30)):
            self.probe_out = ts
            self.hold_win, self.cool_win = [], []
            ev.append(("probe_out", {"eau": tw, "avant": self.last_good.tw}))
            return ev

        s = Sample(ts, tw, self.te, self.wind)
        self.last_good = s
        self.buf.append(s)
        while ts - self.buf[0].ts > self.BUFFER:
            self.buf.popleft()
        sl = slope(self._tail(self.WINDOW))
        if sl is None and len(self.buf) >= 3 and ts - self.buf[-3].ts <= timedelta(hours=2.5):
            sl = slope(list(self.buf)[-3:])          # relevés espacés (anciens historiques)

        if self.declared and ts - self.declared > self.DECLARE_TTL:
            ev.append(("fire_failed", {"allumage": self.declared.isoformat()}))
            self.declared = None

        if self.fire is None:
            if self._fire_starts(s, sl):
                ev.append(("fire_start", self._start_fire(s)))
            else:
                self._learn_hold(s, ev)
                self._learn_cooling(s, ev)
            return ev

        self._update_fire(s, sl, ev)
        return ev

    def _tail(self, span: timedelta) -> list[Sample]:
        """Relevés des `span` dernières heures (le tampon est trié)."""
        out: list[Sample] = []
        if not self.buf:
            return out
        end = self.buf[-1].ts
        for x in reversed(self.buf):
            if end - x.ts > span:
                break
            out.append(x)
        out.reverse()
        return out

    def _fire_starts(self, s: Sample, sl: float | None) -> bool:
        if sl is None:
            return False
        if self.declared:
            rise = self.RISE_DECLARED
        else:
            rise = self.RISE if self.p.hold_high is not None else self.RISE_COLD
        margin = 0.1 if self.declared else 0.3
        above = self.p.hold_high is None or s.tw > self.p.hold_high + margin or sl > 3.0
        low = min(x.tw for x in self._tail(timedelta(hours=2)))
        return sl > rise and above and s.tw >= low + 0.5

    def _start_fire(self, s: Sample) -> dict:
        # base : minimum local en remontant le temps (≤ 3 h)
        pts = self._tail(timedelta(hours=3))
        i = len(pts) - 1
        while i > 0 and pts[i - 1].tw <= pts[i].tw + 0.01:
            i -= 1
        base = pts[i].tw
        # début de montée : passage à base + 0,25 °C (interpolé)
        rise_start = s.ts
        for a, b in zip(pts[i:], pts[i + 1:]):
            if b.tw >= base + 0.25:
                frac = (base + 0.25 - a.tw) / (b.tw - a.tw) if b.tw != a.tw else 1
                rise_start = a.ts + (b.ts - a.ts) * max(0.0, min(1.0, frac))
                break
        f = Fire(rise_start=rise_start, base=base, detected=s.ts)
        if self.declared and rise_start - self.declared < self.DECLARE_TTL:
            f.ignition = min(self.declared, rise_start)
        self.declared = None
        f.peak = f.sig_peak = s.tw
        f.peak_ts = f.last_rise = s.ts
        self.fire = f
        self.hold_win, self.cool_win = [], []
        self._mark_crossings(pts[i:])
        return {"debut_montee": rise_start.isoformat(), "de": base,
                "declare": f.ignition is not None}

    def _mark_crossings(self, pts: list[Sample]) -> None:
        f = self.fire
        for a, b in zip(pts, pts[1:]):
            for g in GRID:
                key = f"{g:.1f}"
                if key not in f.reached and a.tw < g <= b.tw and g > f.base + 0.3:
                    frac = (g - a.tw) / (b.tw - a.tw)
                    f.reached[key] = a.ts + (b.ts - a.ts) * frac

    def _update_fire(self, s: Sample, sl: float | None, ev: list) -> None:
        f = self.fire
        prev = self.buf[-2] if len(self.buf) > 1 else s
        if f.opened is None:
            self._mark_crossings([prev, s])
        if s.tw > f.peak:
            f.peak, f.peak_ts = s.tw, s.ts
        if s.tw >= f.sig_peak + 0.1:
            f.sig_peak, f.last_rise = s.tw, s.ts
        if (f.opened is None and sl is not None and sl < self.OPEN
                and s.tw < f.peak - 0.3):
            f.opened = s.ts
            f.opened_rising = s.ts - f.last_rise < timedelta(minutes=25)
            ev.append(("opened", {"eau": s.tw, "pendant_la_montee": f.opened_rising}))
        if (s.ts - f.last_rise >= self.END_AFTER and (sl is None or sl < 0.3)) \
                or s.ts - f.rise_start > timedelta(hours=10):
            rec = self._finish_fire(s.ts)
            ev.append(("fire_end", rec) if rec else ("fire_discarded", {}))

    # ------------------------------------------------------------ fin de feu
    def _finish_fire(self, now: datetime) -> dict | None:
        f, self.fire = self.fire, None
        self.last_fire_end = now
        if f.peak - f.base < 1.5:               # cycle du maintien, reprise après baignade
            return None
        learn = self._learning(now)
        declared = f.ignition is not None
        ignition = f.ignition or f.rise_start - timedelta(hours=self.p.lag_h)
        seg = [x for x in self.buf if f.rise_start - timedelta(minutes=10) <= x.ts <= now]
        upto = [x for x in seg if x.ts <= f.peak_ts]
        tes = [x.te for x in upto if x.te is not None]
        winds = [x.wind for x in upto if x.wind is not None]
        lo = f.reached.get(f"{math.ceil((f.base + 0.5) * 2) / 2:.1f}")
        hi_g = math.floor((f.peak - 0.5) * 2) / 2
        hi = f.reached.get(f"{hi_g:.1f}")
        rate = None
        if lo and hi and hi > lo:
            rate = round((hi_g - math.ceil((f.base + 0.5) * 2) / 2) / _h(hi, lo), 2)
        rec = {
            "allumage": ignition.isoformat(), "declare": declared,
            "debut_montee": f.rise_start.isoformat(), "de": round(f.base, 2),
            "pic": round(f.peak, 2), "heure_pic": f.peak_ts.isoformat(),
            "duree_pic_min": round(_h(f.peak_ts, ignition) * 60),
            "montee_c_h": rate,
            "ext": round(sum(tes) / len(tes), 1) if tes else None,
            "vent": round(sum(winds) / len(winds), 1) if winds else None,
            "baignade": f.opened is not None, "baignade_pendant_montee": f.opened_rising,
            "atteint": {k: round(_h(v, ignition) * 60) for k, v in sorted(f.reached.items())},
        }
        if not learn:
            return rec if self._is_new(rec) else None
        dense = len(upto) >= 2 and _h(upto[-1].ts, upto[0].ts) / (len(upto) - 1) <= 0.25
        curve = self._extract_curve(f, seg, now) if dense else []
        if curve and sum(v for v in curve if v) * BIN_H > 1.0:
            stop = min(now, f.peak_ts + timedelta(minutes=45), f.opened or now)
            pts = self.heat_points(f, stop)
            if len(pts) >= 4:
                a, sc = self.p.fit_fire(pts, self.usual_fire())
                self.p.merge_curve(curve)
                rec.update(courbe_apprise=True, chaleur_rel=round(a, 2), duree_rel=round(sc, 2))
        if declared:
            lag = _h(f.rise_start, f.ignition)
            if 0.0 <= lag <= 1.5:
                a = 0.5 if self.p.n_lag < 3 else 0.3
                self.p.lag_h = round((1 - a) * self.p.lag_h + a * lag, 3)
                self.p.n_lag += 1
                rec["delai_min"] = round(lag * 60)
        self.fires.append(rec)
        del self.fires[:-500]
        return rec

    def _is_new(self, rec: dict) -> bool:
        """Rejeu : un feu déjà enregistré n'est pas compté deux fois."""
        t = datetime.fromisoformat(rec["debut_montee"])
        for r in self.fires[-20:]:
            if abs(_h(datetime.fromisoformat(r["debut_montee"]), t)) < 1:
                return False
        self.fires.append(rec)
        return True

    def _extract_curve(self, f: Fire, seg: list[Sample], now: datetime) -> list[float | None]:
        """Apport du feu P = dT/dt + k(T − T_ext), par pas de 5 min depuis la montée."""
        if len(seg) < 4:
            return []
        stop = min(now, f.peak_ts + timedelta(minutes=45))
        if f.opened:
            stop = min(stop, f.opened - timedelta(minutes=10))
        n = int(_h(stop, f.rise_start) / BIN_H)
        if n < 6:
            return []
        grid = [f.rise_start + timedelta(minutes=BIN_MIN * i) for i in range(n + 2)]
        temps = [interp(seg, t) for t in grid]
        te_list = [x.te for x in seg if x.te is not None]
        te = sum(te_list) / len(te_list) if te_list else None
        if te is None:
            return []
        wind = [x.wind for x in seg if x.wind is not None]
        k = self.p.k(sum(wind) / len(wind) if wind else None)
        raw = []
        for i in range(n):
            lo, hi = max(i - 1, 0), i + 1
            dtdt = (temps[hi] - temps[lo]) / ((hi - lo) * BIN_H)
            raw.append(max(0.0, dtdt + k * (temps[i] - te)))
        smooth = [sum(raw[max(0, i - 1):i + 2]) / len(raw[max(0, i - 1):i + 2])
                  for i in range(len(raw))]
        out: list[float | None] = [round(v, 3) for v in smooth]
        if f.opened is None:                    # feu suivi jusqu'au bout : après, rien
            out += [0.0] * (CURVE_BINS - len(out))
        return out[:CURVE_BINS]

    # ------------------------------------------------------------ maintien, pertes
    def _learn_hold(self, s: Sample, ev: list) -> None:
        if self.last_fire_end and s.ts - self.last_fire_end < timedelta(hours=1):
            return
        self.hold_win.append(s)
        span = s.ts - self.hold_win[0].ts
        if span < self.HOLD_SPAN:
            return
        win, self.hold_win = self.hold_win, [s]
        vals = sorted(x.tw for x in win)
        tes = [x.te for x in win if x.te is not None]
        sl = slope(win)
        if len(vals) < 8 or vals[-1] - vals[0] > 1.2 or sl is None or abs(sl) > 0.1:
            return
        mean = sum(vals) / len(vals)
        if tes and mean - sum(tes) / len(tes) < 8:      # simple équilibre avec l'air
            return
        low = vals[max(0, len(vals) // 10)]
        high = vals[-1]
        if not self._learning(s.ts):
            return
        p = self.p
        if p.hold_low is None or abs(low - p.hold_low) > 1.0:
            p.hold_low, p.hold_high = low, high
        else:
            p.hold_low = round(0.7 * p.hold_low + 0.3 * low, 3)
            p.hold_high = round(0.7 * p.hold_high + 0.3 * high, 3)
        p.hold_seen = s.ts.isoformat()
        p.n_hold += 1
        ev.append(("hold_learned", {"bas": p.hold_low, "haut": p.hold_high}))

    def _learn_cooling(self, s: Sample, ev: list) -> None:
        ok = (s.te is not None
              and (self.last_fire_end is None
                   or s.ts - self.last_fire_end >= timedelta(minutes=30))
              and (self.p.hold_high is None or s.tw > self.p.hold_high + 0.4)
              and (not self.use_wind or s.wind is not None))
        if not ok:
            self.cool_win = []
            return
        self.cool_win.append(s)
        span = s.ts - self.cool_win[0].ts
        if span < self.COOL_SPAN:
            return
        win, self.cool_win = self.cool_win, [s]
        sl = slope(win, min_span_h=1.5)
        if sl is None or len(win) < 3:
            return
        if any(b.tw - a.tw > 0.07 for a, b in zip(win, win[1:])):
            return                                   # une remontée : chauffage ou feu
        dT = sum(x.tw - x.te for x in win) / len(win)
        if dT < 5 or sl >= 0:
            return
        y = -sl / dT
        x = sum(w.wind for w in win) / len(win) if self.use_wind else 0.0
        self.last_k = {"fin": s.ts.isoformat(), "k_mesure": round(y, 5),
                       "ecart_moyen": round(dT, 1), "vent": round(x, 1)}
        if 0.003 < y < 0.08 and self._learning(s.ts):
            self.p.add_k_obs(y, x, _h(win[-1].ts, win[0].ts))
            ev.append(("k_learned", self.last_k))

    # ------------------------------------------------------------ prévisions
    def heat_points(self, f: Fire, until: datetime, step_min: int = 10) -> list[tuple[float, float]]:
        """Chaleur reçue depuis le début de la montée, tous les `step_min` :
        (T − T_départ) + pertes cumulées k(T − T_ext)."""
        seg = [x for x in self.buf if f.rise_start - timedelta(minutes=15) <= x.ts <= until]
        if len(seg) < 3:
            return []
        t0 = f.base + 0.25
        pts, lost = [], 0.0
        prev_t, prev_T = f.rise_start, t0
        n = int(_h(until, f.rise_start) * 60 / step_min)
        for i in range(1, n + 1):
            t = f.rise_start + timedelta(minutes=step_min * i)
            T = interp(seg, t)
            near = min(seg, key=lambda x: abs(x.ts - t))
            te = near.te if near.te is not None else self.te
            if te is None:
                return []
            lost += self.p.k(near.wind) * ((T + prev_T) / 2 - te) * _h(t, prev_t)
            pts.append((_h(t, f.rise_start), T - t0 + lost))
            prev_t, prev_T = t, T
        return pts

    def usual_fire(self) -> tuple[float, float]:
        """(a, s) typiques : moyenne géométrique des 10 derniers feux mesurés.

        La courbe moyenne « étale » les feux (pics décalés) ; ce recentrage
        corrige le biais qui en résulte sur le pic d'un feu habituel."""
        fits = [(r["chaleur_rel"], r["duree_rel"]) for r in self.fires[-30:]
                if r.get("chaleur_rel")][-10:]
        if len(fits) < 3:
            return 1.0, 1.0
        ga = math.exp(sum(math.log(a) for a, _ in fits) / len(fits))
        gs = math.exp(sum(math.log(x) for _, x in fits) / len(fits))
        return round(min(max(ga, 0.6), 1.6), 3), round(min(max(gs, 0.6), 1.6), 3)

    def fire_fit(self, now: datetime) -> tuple[float, float]:
        """(a, s) du feu en cours : a = chaleur, s = durée, relatives à la courbe moyenne."""
        p = self.p
        f = self.fire
        center = self.usual_fire()
        if not f or _h(now, f.rise_start) < 1 / 3:
            return center
        key = (f.rise_start, len(self.buf), self.buf[-1].ts if self.buf else None)
        if self._fit_cache and self._fit_cache[0] == key:
            return self._fit_cache[1]
        pts = self.heat_points(f, f.opened or now)
        res = p.fit_fire(pts, center) if len(pts) >= 2 else center
        self._fit_cache = (key, res)
        return res

    def intensity(self, now: datetime) -> float | None:
        """Vitesse de chauffe du feu en cours / feu habituel (1 = comme d'habitude)."""
        if not self.fire or _h(now, self.fire.rise_start) < 1 / 3:
            return None
        a, s = self.fire_fit(now)
        a0, s0 = self.usual_fire()
        return round((a / s) / (a0 / s0), 2)

    def predict(self, now: datetime, tw: float, te: float, wind: float | None,
                targets: list[float], traj_every: int = 0, a_mult: float = 1.0) -> dict:
        """Simule le feu en cours, ou un feu allumé maintenant.

        a_mult : feu plus ou moins généreux que prévu (fourchette).

        Retourne pic, heure du pic (h depuis maintenant), passage de chaque
        cible (h, négatif si déjà passé pendant ce feu) et trajectoire."""
        p = self.p
        k = p.k(wind)
        floor = p.floor(now)
        f = self.fire
        if f:
            tau0 = _h(now, f.rise_start)
            a, s = self.fire_fit(now)
        else:
            tau0 = -(p.lag_h if not self.declared else max(0.0, p.lag_h - _h(now, self.declared)))
            a, s = self.usual_fire()
        cross: dict[float, float | None] = {}
        for g in targets:
            key = f"{g:.1f}"
            if f and key in f.reached:
                cross[g] = _h(f.reached[key], now)
            elif tw >= g:
                cross[g] = 0.0
        T, t, peak, peak_h, traj, i = tw, 0.0, tw, 0.0, [(0.0, tw)], 0
        horizon = max(p.curve_length_h() * s - tau0, 0) + 1.0
        while t < horizon:
            P = a * a_mult / s * p.p_at((tau0 + t) / s)
            T += (P - k * (T - te)) * SIM_STEP_H
            if floor is not None:
                T = max(T, floor)
            t += SIM_STEP_H
            i += 1
            for g in targets:
                if g not in cross and T >= g:
                    cross[g] = t
            if T > peak:
                peak, peak_h = T, t
            if traj_every and i % traj_every == 0:
                traj.append((t, T))
        return {"peak": peak, "peak_h": peak_h, "cross": cross, "a": a, "s": s,
                "scale": self.intensity(now) if f else 1.0,
                "traj": [x for x in traj if x[0] <= peak_h + 0.5]}

    def cooling(self, now: datetime, tw: float, te: float, wind: float | None,
                below: float) -> float | None:
        """Heures avant que l'eau (sans feu) passe sous `below` ; None si jamais."""
        k = self.p.k(wind)
        floor = self.p.floor(now)
        if tw < below or te >= below or (floor is not None and floor >= below):
            return None
        return math.log((tw - te) / (below - te)) / k
