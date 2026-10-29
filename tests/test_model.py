"""Tests du moteur sur un bain simulé (sans Home Assistant)."""
from __future__ import annotations

import importlib.util
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_path = Path(__file__).resolve().parent.parent / "custom_components/bain_nordique/model.py"
_spec = importlib.util.spec_from_file_location("bain_model", _path)
model = importlib.util.module_from_spec(_spec)
sys.modules["bain_model"] = model
_spec.loader.exec_module(model)

T0 = datetime(2026, 10, 1, tzinfo=UTC)
K = 0.015
TE = 10.0


def simulate(fires_at_h: list[float], hours: float, probe_out: tuple[float, float] | None = None,
             fire_scale: float = 1.0):
    """Bain simulé : maintien 33,0–33,7 °C, feux selon la courbe par défaut, relevés au
    changement de 0,0625 °C comme une DS18B20."""
    p = model.Params()
    out, T, heater, last_pub = [], 33.3, False, None
    t, dt = 0.0, 1 / 60
    while t < hours:
        P = sum(fire_scale * p.p_at(t - s) for s in fires_at_h)
        if T <= 33.0:
            heater = True
        elif T >= 33.7:
            heater = False
        T += (P + (1.2 if heater else 0.0) - K * (T - TE)) * dt
        q = round(T / 0.0625) * 0.0625
        if probe_out and probe_out[0] <= t < probe_out[1]:
            q = round(TE / 0.0625) * 0.0625
        if q != last_pub:
            out.append((T0 + timedelta(hours=t), q))
            last_pub = q
        t += dt
    return out


def run(samples, engine=None):
    eng = engine or model.Engine(model.Params(), [])
    eng.set_outdoor(TE)
    events = []
    for ts, v in samples:
        events += [(ts, n, d) for n, d in eng.feed(ts, v)]
    return eng, events


def names(events):
    return [n for _, n, _ in events]


def test_hold_learned_and_no_false_fire():
    eng, ev = run(simulate([], 30))
    assert "fire_start" not in names(ev)
    assert eng.p.hold_low is not None
    assert 32.8 <= eng.p.hold_low <= 33.2
    assert 33.5 <= eng.p.hold_high <= 33.9


def test_fire_detected_and_recorded():
    eng, ev = run(simulate([20.0], 30))
    n = names(ev)
    assert n.count("fire_start") == 1 and n.count("fire_end") == 1
    rec = eng.fires[-1]
    assert rec["pic"] > 38
    assert "38.0" in rec["atteint"]
    start = [ts for ts, name, _ in ev if name == "fire_start"][0]
    assert abs((start - (T0 + timedelta(hours=20))).total_seconds()) < 3600


def test_probe_out_ignored():
    eng, ev = run(simulate([], 30, probe_out=(15.0, 18.0)))
    n = names(ev)
    assert "probe_out" in n and "probe_back" in n
    assert "fire_start" not in n


def test_loss_coefficient_learned():
    # refroidissement sans maintien : le bain part de 40 °C
    samples, T = [], 40.0
    for i in range(12 * 60):
        T += -K * (T - TE) / 60
        samples.append((T0 + timedelta(minutes=i), round(T / 0.0625) * 0.0625))
    eng, _ = run(samples)
    k0, _ = eng.p.k_fit()
    assert eng.p.n_k >= 3
    assert abs(k0 - K) / K < 0.15


def test_prediction_if_fire_now_matches_simulation():
    eng, _ = run(simulate([], 12))
    now = T0 + timedelta(hours=12)
    r = eng.predict(now, 33.3, TE, None, [37.0])
    real = simulate([12.0 + eng.p.lag_h], 20)
    t37 = next(ts for ts, v in real if v >= 37.0)
    pred = now + timedelta(hours=r["cross"][37.0])
    assert abs((pred - t37).total_seconds()) < 20 * 60


def test_weak_fire_adapts_during_fire():
    samples = simulate([10.0], 16, fire_scale=0.7)
    eng = model.Engine(model.Params(), [])
    eng.set_outdoor(TE)
    stop = T0 + timedelta(hours=12, minutes=10)
    for ts, v in samples:
        if ts > stop:
            break
        eng.feed(ts, v)
    assert eng.fire is not None
    r = eng.predict(stop, eng.last_good.tw, TE, None, [38.0])
    true_peak = max(v for _, v in samples)
    assert abs(r["peak"] - true_peak) < 0.6
    assert eng.intensity(stop) < 0.95


def test_params_roundtrip():
    p = model.Params()
    p.add_k_obs(0.02, 5.0, 2.0)
    q = model.Params.from_dict(p.as_dict())
    assert q.as_dict() == p.as_dict()
    assert math.isclose(q.k(None), p.k(None))
