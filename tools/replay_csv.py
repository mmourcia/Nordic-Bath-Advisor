"""Rejoue un export CSV de l'historique Home Assistant dans le modèle.

    python tools/replay_csv.py history.csv [--water sensor.x] [--outdoor sensor.y]
                               [--wind sensor.z] [--target 38] [--passes 2]

Export : Historique → choisir les entités → ⋮ → Télécharger les données.
Affiche les feux détectés, les paramètres appris et, pour chaque feu, l'écart
entre la prévision (au démarrage, à +30 min, à +60 min) et la réalité.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "model", Path(__file__).resolve().parent.parent / "custom_components/bain_nordique/model.py")
model = importlib.util.module_from_spec(_spec)
sys.modules["model"] = model
_spec.loader.exec_module(model)


def load(path: str) -> dict[str, list[tuple[datetime, float]]]:
    series: dict[str, list] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                v = float(row["state"])
            except ValueError:
                continue
            ts = datetime.fromisoformat(row["last_changed"].replace("Z", "+00:00"))
            series.setdefault(row["entity_id"], []).append((ts, v))
    for s in series.values():
        s.sort()
    return series


def guess(series: dict, *words: str) -> str | None:
    for eid in series:
        if all(w in eid for w in words):
            return eid
    return None


def replay(series, water, outdoor, wind, target, params=None, verbose=True):
    p = params or model.Params()
    eng = model.Engine(p, [], use_wind=bool(wind))
    stream = [(ts, "w", v) for ts, v in series[water]]
    stream += [(ts, "o", v) for ts, v in series.get(outdoor, [])]
    stream += [(ts, "v", v) for ts, v in series.get(wind, [])] if wind else []
    stream.sort(key=lambda x: (x[0], x[1] != "o"))
    checks: list[dict] = []
    pending: list = []
    for ts, kind, v in stream:
        if kind == "o":
            eng.set_outdoor(v)
            continue
        if kind == "v":
            eng.set_wind(v)
            continue
        for name, data in eng.feed(ts, v):
            if verbose and name not in ("k_learned", "hold_learned"):
                print(f"{ts:%m-%d %H:%M}  {name:15s} {json.dumps(data, default=str)[:150]}")
            if name == "fire_start":
                pending = [ts, ts + timedelta(minutes=30), ts + timedelta(minutes=60)]
                checks.append({"start": ts, "preds": []})
            if name == "fire_end" and checks:
                checks[-1]["rec"] = data
        while pending and eng.fire and ts >= pending[0] and eng.te is not None:
            r = eng.predict(ts, v, eng.te, eng.wind, [target])
            c = r["cross"].get(target)
            checks[-1]["preds"].append({
                "at": ts, "peak": r["peak"], "peak_t": ts + timedelta(hours=r["peak_h"]),
                "cross": ts + timedelta(hours=c) if c is not None else None,
                "scale": r["scale"]})
            pending.pop(0)
    return eng, checks


def report(eng, checks, target):
    key = f"{target:.1f}"
    print("\n=== Feux")
    for c in checks:
        rec = c.get("rec")
        if not rec:
            continue
        ign = datetime.fromisoformat(rec["allumage"])
        real = rec["atteint"].get(key)
        real_t = ign + timedelta(minutes=real) if real is not None else None
        line = (f"{rec['debut_montee'][5:16]} {rec['de']:.1f}→{rec['pic']:.1f} °C "
                f"pic {rec['heure_pic'][11:16]} montée {rec['montee_c_h']} °C/h "
                f"ext {rec['ext']} | {target} °C réel {real_t:%H:%M}" if real_t else
                f"{rec['debut_montee'][5:16]} {rec['de']:.1f}→{rec['pic']:.1f} °C (cible non atteinte)")
        print(line)
        real_peak_t = datetime.fromisoformat(rec["heure_pic"])
        for pr in c["preds"]:
            dc = (round((pr["cross"] - real_t).total_seconds() / 60)
                  if pr["cross"] and real_t else None)
            print(f"   prévu à {pr['at']:%H:%M} : {target} °C à "
                  f"{pr['cross']:%H:%M} ({dc:+d} min)" if dc is not None else
                  f"   prévu à {pr['at']:%H:%M} : cible —", end="")
            print(f" | pic {pr['peak']:.1f} ({pr['peak'] - rec['pic']:+.1f} °C) à "
                  f"{pr['peak_t']:%H:%M} ({(pr['peak_t'] - real_peak_t).total_seconds() / 60:+.0f} min)"
                  f" intensité {pr['scale']}")
    p = eng.p
    k0, kw = p.k_fit()
    print(f"\n=== Paramètres : k0={k0:.4f}/h kw={kw:.5f} ({p.n_k} fenêtres) "
          f"délai={p.lag_h * 60:.0f} min maintien={p.hold_low}–{p.hold_high} ({p.n_hold}) "
          f"courbes={p.n_curve}")
    print("courbe :", [round(x, 1) for x in p.curve[:40]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--water")
    ap.add_argument("--outdoor")
    ap.add_argument("--wind")
    ap.add_argument("--target", type=float, default=38.0)
    ap.add_argument("--passes", type=int, default=2,
                    help="rejouer plusieurs fois : la 2e passe prévoit avec ce qui a été appris")
    a = ap.parse_args()
    series = load(a.csv)
    water = a.water or guess(series, "temperature_eau")
    outdoor = a.outdoor or guess(series, "exterieur")
    print(f"eau={water} ext={outdoor} vent={a.wind}")
    params = None
    for n in range(a.passes):
        last = n == a.passes - 1
        eng, checks = replay(series, water, outdoor, a.wind, a.target, params, verbose=last)
        params = model.Params.from_dict(json.loads(json.dumps(eng.p.as_dict())))
        params.n_curve = params.n_k = params.n_hold = params.n_lag = 0
    report(eng, checks, a.target)


if __name__ == "__main__":
    main()
