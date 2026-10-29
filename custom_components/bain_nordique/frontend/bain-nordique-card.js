/*
 * Carte Lovelace « Bain nordique » — chargée automatiquement par l'intégration.
 *
 *   type: custom:bain-nordique-card
 *   # optionnel :
 *   title: Bain nordique
 *   hours: 12            # historique affiché sur la courbe
 *   entity: sensor.bain_nordique_etat   # si plusieurs bains
 *
 * Les entités sont trouvées seules via l'attribut `entites` du capteur d'état.
 */
const VERSION = "1.1.0";

const STATE_LABEL = {
  hold: "Maintien électrique",
  cooling: "Refroidissement",
  lit: "Feu allumé",
  fire: "Feu en cours",
  probe_out: "Sonde hors de l'eau",
};
const STATE_ICON = {
  hold: "mdi:thermostat",
  cooling: "mdi:thermometer-chevron-down",
  lit: "mdi:fire-circle",
  fire: "mdi:fire",
  probe_out: "mdi:alert",
};

const num = (v, d = 1) =>
  v === null || v === undefined || isNaN(v) ? "—" : Number(v).toFixed(d).replace(".", ",");

const duration = (min) => {
  if (min === null || min === undefined || isNaN(min)) return "—";
  min = Math.round(Number(min));
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
};

class BainNordiqueCard extends HTMLElement {
  setConfig(config) {
    this._config = { hours: 12, ...config };
    this._history = null;
    this._historyAt = 0;
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    }
    const main = this._findMain();
    if (main && Date.now() - this._historyAt > 5 * 60 * 1000) {
      this._historyAt = Date.now();
      this._loadHistory(main.attributes.sonde_eau);
    }
    const key = this._renderKey(main);
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._render(main);
    }
  }

  // ------------------------------------------------------------ données
  _findMain() {
    const h = this._hass;
    if (this._config.entity) return h.states[this._config.entity];
    return Object.values(h.states).find(
      (s) => s.attributes && s.attributes.integration === "bain_nordique" && s.attributes.entites
    );
  }

  _ent(key) {
    const main = this._main;
    const id = main && main.attributes.entites && main.attributes.entites[key];
    return id ? this._hass.states[id] : undefined;
  }

  _val(key) {
    const s = this._ent(key);
    if (!s || s.state === "unknown" || s.state === "unavailable") return null;
    return s.state;
  }

  _renderKey(main) {
    if (!main) return "none";
    const ids = Object.values(main.attributes.entites || {});
    ids.push(main.attributes.sonde_eau);
    return ids.map((id) => {
      const s = this._hass.states[id];
      return s ? s.last_updated : "";
    }).join("|") + `|${this._historyAt}|${this._history ? this._history.length : 0}`;
  }

  async _loadHistory(entityId) {
    if (!entityId) return;
    const start = new Date(Date.now() - this._config.hours * 3600 * 1000);
    try {
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        entity_ids: [entityId],
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      const rows = res[entityId] || [];
      this._history = rows
        .map((r) => [((r.lu || r.lc) * 1000), parseFloat(r.s)])
        .filter((p) => !isNaN(p[1]) && !isNaN(p[0]));
    } catch (e) {
      this._history = [];
    }
    this._lastKey = null;
    if (this._hass) this.hass = this._hass;
  }

  _time(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return "—";
    const lang = (this._hass.locale && this._hass.locale.language) || "fr";
    return d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  }

  // ------------------------------------------------------------ actions
  _onClick(ev) {
    const el = ev.composedPath().find((x) => x.dataset && x.dataset.action);
    if (!el) return;
    const action = el.dataset.action;
    const main = this._main;
    const ents = (main && main.attributes.entites) || {};
    if (action === "press") {
      this._hass.callService("button", "press", { entity_id: ents[el.dataset.key] });
    } else if (action === "target") {
      const cur = parseFloat(this._val("cible")) || 38;
      const value = Math.min(44, Math.max(30, cur + parseFloat(el.dataset.step)));
      this._hass.callService("number", "set_value", { entity_id: ents.cible, value });
    } else if (action === "more") {
      const id = el.dataset.entity || ents[el.dataset.key];
      if (id) {
        this.dispatchEvent(new CustomEvent("hass-more-info", {
          detail: { entityId: id }, bubbles: true, composed: true,
        }));
      }
    }
  }

  // ------------------------------------------------------------ rendu
  _render(main) {
    this._main = main;
    if (!main) {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="empty">
        Intégration Bain nordique introuvable : ajoute-la dans Paramètres → Appareils et services.
      </div></ha-card>`;
      return;
    }
    const a = main.attributes;
    const state = main.state;
    const water = this._hass.states[a.sonde_eau];
    const tw = water ? parseFloat(water.state) : null;
    const target = parseFloat(this._val("cible")) || 38;
    const inFire = state === "fire";
    const ready = this._val("bain_pret") === "on";
    const tgt = this._ent("heure_cible");
    const peak = this._ent("pic_prevu");
    const tgtA = (tgt && tgt.attributes) || {};
    const peakA = (peak && peak.attributes) || {};
    const ifNow = tgtA.si_feu_maintenant;
    const intensity = this._val("intensite_feu");
    const below = this._val("sous_la_cible");
    const title = this._config.title || "Bain nordique";
    const stateCls = { fire: "fire", lit: "fire", probe_out: "alert", hold: "hold", cooling: "cool" }[state] || "";

    let prediction;
    if (state === "probe_out") {
      prediction = `<div class="pred alert">La sonde semble hors de l'eau : prévisions en pause.</div>`;
    } else if (ready && !inFire) {
      prediction = `<div class="pred ok"><ha-icon icon="mdi:check-circle"></ha-icon>
        <div><b>Bain prêt</b>${below ? ` — au-dessus de ${num(target, 1)} °C jusqu'à <b>${this._time(below)}</b>` : ""}</div></div>`;
    } else {
      const tVal = this._val("heure_cible");
      const reached = inFire && ready;
      const head = ifNow ? "Si tu allumes maintenant" : "Feu en cours";
      const range = tgtA.au_plus_tot && tgtA.au_plus_tard
        ? `<span class="range">entre ${this._time(tgtA.au_plus_tot)} et ${this._time(tgtA.au_plus_tard)}</span>` : "";
      const targetLine = reached
        ? `<div class="big ok">${num(target, 1)} °C atteint ✓</div>`
        : tVal
          ? `<div class="big">${num(target, 1)} °C à <b>${this._time(tVal)}</b></div>
             <div class="sub">dans ${duration(this._val("duree_avant_cible"))} ${range}</div>`
          : `<div class="big">${num(target, 1)} °C hors de portée</div>`;
      prediction = `<div class="pred">
        <div class="pred-head">${head}${intensity ? ` · feu à <b>${intensity} %</b> de l'habitude` : ""}</div>
        ${targetLine}
        <div class="sub">Pic <b>${num(peak ? peak.state : null, 1)} °C</b> vers ${this._time(peakA.heure)}
          ${peakA.fourchette_basse ? `<span class="range">(${num(peakA.fourchette_basse, 1)} – ${num(peakA.fourchette_haute, 1)} °C)</span>` : ""}</div>
      </div>`;
    }

    const fireButtons = inFire || state === "lit"
      ? `<button class="ghost" data-action="press" data-key="pas_de_feu"><ha-icon icon="mdi:fire-off"></ha-icon>Pas de feu</button>`
      : "";
    const fireBtn = !inFire && state !== "lit"
      ? `<button class="primary" data-action="press" data-key="feu_allume"><ha-icon icon="mdi:fire"></ha-icon>J'allume le feu</button>`
      : state === "lit"
        ? `<span class="note">Allumage noté, en attente de la montée…</span>`
        : "";

    const stat = (key, label, fmt) => {
      const v = this._val(key);
      return `<div class="stat" data-action="more" data-key="${key}">
        <div class="stat-v">${v === null ? "—" : fmt(v)}</div><div class="stat-l">${label}</div></div>`;
    };
    const te = a.temperature_exterieure;

    this.shadowRoot.innerHTML = `${this._style()}
      <ha-card>
        <div class="top">
          <div class="title">${title}</div>
          <div class="chip ${stateCls}" data-action="more" data-key="etat">
            <ha-icon icon="${STATE_ICON[state] || "mdi:hot-tub"}"></ha-icon>${STATE_LABEL[state] || "—"}
          </div>
        </div>
        <div class="hero">
          <div class="temp ${ready ? "ok" : ""}" data-action="more" data-entity="${a.sonde_eau}">
            ${num(tw, 1)}<span>°C</span>
          </div>
          <div class="target">
            <div class="target-l">Cible</div>
            <div class="target-ctl">
              <button class="round" data-action="target" data-step="-0.5">−</button>
              <div class="target-v">${num(target, 1)} °C</div>
              <button class="round" data-action="target" data-step="0.5">+</button>
            </div>
            <div class="ext">Extérieur ${num(te, 1)} °C · pertes ${num(this._val("pertes_actuelles"), 2)} °C/h</div>
          </div>
        </div>
        ${prediction}
        ${this._chart(target, tgtA.trajectoire || [], a, tw)}
        <div class="actions">${fireBtn}${fireButtons}</div>
        <div class="stats">
          ${stat("feux_30_jours", "feux sur 30 jours", (v) => v)}
          ${stat("temps_moyen_38", "moyenne → 38 °C", duration)}
          ${stat("temps_moyen_39", "moyenne → 39 °C", duration)}
          ${stat("montee_moyenne", "montée moyenne", (v) => `${num(v, 1)} °C/h`)}
          ${stat("dernier_feu", "pic du dernier feu", (v) => `${num(v, 1)} °C`)}
          ${stat("nombre_feux", "feux au total", (v) => v)}
        </div>
      </ha-card>`;
  }

  _chart(target, traj, a, tw) {
    const now = Date.now();
    const meas = (this._history || []).slice();
    if (tw !== null && !isNaN(tw)) meas.push([now, tw]);
    const pred = traj.map((p) => [new Date(p[0]).getTime(), p[1]]).filter((p) => p[0] >= now - 60000);
    if (meas.length < 2 && pred.length < 2) return "";
    const x0 = now - this._config.hours * 3600 * 1000;
    const x1 = Math.max(now + 2 * 3600 * 1000, pred.length ? pred[pred.length - 1][0] : 0);
    const vals = meas.filter((p) => p[0] >= x0).map((p) => p[1]).concat(pred.map((p) => p[1]), [target]);
    if (a.maintien_bas) vals.push(a.maintien_bas);
    let y0 = Math.floor(Math.min(...vals) - 0.5);
    let y1 = Math.ceil(Math.max(...vals) + 0.5);
    if (y1 - y0 < 4) y1 = y0 + 4;
    const W = 400, H = 160, L = 24, R = 4, T = 6, B = 16;
    const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    const path = (pts) => pts.filter((p) => p[0] >= x0 && p[0] <= x1)
      .map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    const ticksY = [];
    const stepY = y1 - y0 > 10 ? 4 : 2;
    for (let v = Math.ceil(y0 / stepY) * stepY; v <= y1; v += stepY) {
      ticksY.push(`<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>
        <text class="tick" x="${L - 4}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`);
    }
    const ticksX = [];
    const step = (x1 - x0) / 3600000 > 14 ? 4 : 2;
    const first = new Date(x0);
    first.setMinutes(0, 0, 0);
    for (let t = first.getTime() + 3600000; t < x1; t += 3600000) {
      const d = new Date(t);
      if (d.getHours() % step) continue;
      ticksX.push(`<text class="tick" x="${X(t)}" y="${H - 5}" text-anchor="middle">${d.getHours()}h</text>`);
    }
    const hold = a.maintien_bas && a.maintien_haut
      ? `<rect class="hold" x="${L}" width="${W - L - R}" y="${Y(a.maintien_haut)}" height="${Math.max(1, Y(a.maintien_bas) - Y(a.maintien_haut))}"/>`
      : "";
    return `<div class="chart">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Température de l'eau et prévision">
        ${ticksY.join("")}${hold}
        <line class="tgt" x1="${L}" x2="${W - R}" y1="${Y(target)}" y2="${Y(target)}"/>
        <line class="now" x1="${X(now)}" x2="${X(now)}" y1="${T}" y2="${H - B}"/>
        <path class="meas" d="${path(meas)}"/>
        <path class="pred-l" d="${path(pred)}"/>
        ${ticksX.join("")}
      </svg>
      <div class="legend"><span class="lg meas"></span>mesurée<span class="lg pred-l"></span>prévue
        <span class="lg tgt"></span>cible${hold ? `<span class="lg hold"></span>maintien` : ""}</div>
    </div>`;
  }

  _style() {
    return `<style>
      ha-card { padding: 16px; overflow: hidden; }
      .empty { color: var(--secondary-text-color); }
      .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
      .title { font-size: 1.1em; font-weight: 500; color: var(--primary-text-color); }
      .chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px 4px 6px;
        border-radius: 16px; font-size: .85em; cursor: pointer;
        background: var(--secondary-background-color); color: var(--primary-text-color); }
      .chip ha-icon { --mdc-icon-size: 18px; }
      .chip.fire { background: rgba(255, 112, 40, .18); color: var(--state-climate-heat-color, #ff7028); }
      .chip.alert { background: rgba(219, 68, 55, .18); color: var(--error-color, #db4437); }
      .chip.hold { color: var(--primary-color); }
      .hero { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 10px 0 6px; }
      .temp { font-size: 3.4em; font-weight: 300; line-height: 1; cursor: pointer; color: var(--primary-text-color); }
      .temp span { font-size: .4em; margin-left: 2px; color: var(--secondary-text-color); }
      .temp.ok { color: var(--success-color, #43a047); }
      .target { text-align: right; }
      .target-l, .ext { font-size: .8em; color: var(--secondary-text-color); }
      .target-ctl { display: flex; align-items: center; justify-content: flex-end; gap: 6px; margin: 2px 0; }
      .target-v { font-size: 1.3em; min-width: 72px; text-align: center; color: var(--primary-text-color); }
      button { font: inherit; cursor: pointer; border: none; }
      .round { width: 30px; height: 30px; border-radius: 50%; font-size: 1.1em;
        background: var(--secondary-background-color); color: var(--primary-text-color); }
      .pred { padding: 10px 12px; border-radius: 12px; margin: 8px 0;
        background: var(--secondary-background-color); color: var(--primary-text-color); }
      .pred.ok { display: flex; gap: 8px; align-items: center; background: rgba(67, 160, 71, .15); }
      .pred.ok ha-icon { color: var(--success-color, #43a047); }
      .pred.alert { background: rgba(219, 68, 55, .15); color: var(--error-color, #db4437); }
      .pred-head { font-size: .8em; color: var(--secondary-text-color); margin-bottom: 2px; }
      .big { font-size: 1.35em; }
      .big.ok { color: var(--success-color, #43a047); }
      .sub { font-size: .9em; color: var(--secondary-text-color); margin-top: 2px; }
      .sub b { color: var(--primary-text-color); font-weight: 500; }
      .range { opacity: .8; }
      .chart svg { width: 100%; height: auto; display: block; }
      .grid { stroke: var(--divider-color); stroke-width: 1; }
      .tick { fill: var(--secondary-text-color); font-size: 11px; }
      .hold { fill: var(--primary-color); opacity: .08; }
      .tgt { stroke: var(--success-color, #43a047); stroke-dasharray: 4 4; stroke-width: 1.2; }
      .now { stroke: var(--secondary-text-color); stroke-width: 1; opacity: .5; }
      path.meas { fill: none; stroke: var(--primary-color); stroke-width: 2.2; vector-effect: non-scaling-stroke; }
      path.pred-l { fill: none; stroke: var(--state-climate-heat-color, #ff7028); stroke-width: 2.2;
        stroke-dasharray: 6 4; vector-effect: non-scaling-stroke; }
      .tgt, .now, .grid { vector-effect: non-scaling-stroke; }
      .legend { display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
        font-size: .75em; color: var(--secondary-text-color); margin-top: 2px; }
      .lg { display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin-left: 6px; }
      .lg.meas { background: var(--primary-color); }
      .lg.pred-l { background: var(--state-climate-heat-color, #ff7028); }
      .lg.tgt { background: var(--success-color, #43a047); }
      .lg.hold { background: var(--primary-color); opacity: .3; height: 8px; }
      .actions { display: flex; gap: 8px; margin: 12px 0 4px; flex-wrap: wrap; align-items: center; }
      .actions button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 18px; }
      .actions ha-icon { --mdc-icon-size: 18px; }
      .primary { background: var(--state-climate-heat-color, #ff7028); color: #fff; }
      .ghost { background: transparent; color: var(--secondary-text-color); border: 1px solid var(--divider-color) !important; }
      .note { font-size: .85em; color: var(--secondary-text-color); }
      .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
      .stat { padding: 8px; border-radius: 10px; cursor: pointer; background: var(--secondary-background-color); }
      .stat-v { font-size: 1.05em; color: var(--primary-text-color); }
      .stat-l { font-size: .72em; color: var(--secondary-text-color); }
      @media (max-width: 420px) { .stats { grid-template-columns: repeat(2, 1fr); } .temp { font-size: 2.6em; }
        .target-v { min-width: 56px; font-size: 1.1em; } .ext { max-width: 150px; } }
    </style>`;
  }
}

if (!customElements.get("bain-nordique-card")) {
  customElements.define("bain-nordique-card", BainNordiqueCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "bain-nordique-card",
    name: "Bain nordique",
    description: "Température, prévision de chauffe et statistiques du bain nordique",
    preview: true,
  });
  console.info(`%c BAIN-NORDIQUE-CARD %c ${VERSION} `, "background:#ff7028;color:#fff", "");
}
