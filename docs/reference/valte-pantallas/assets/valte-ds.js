/* @ds-bundle: {"format":4,"namespace":"Valte","components":[{"name":"Button"},{"name":"StatusBadge"},{"name":"SeverityMeter"},{"name":"TextField"},{"name":"CrisisGate"},{"name":"CrisisCard"},{"name":"EntityCard"},{"name":"ResourceMeter"},{"name":"ActionItem"},{"name":"SignalItem"}]} */
(function () {
  var R = window.React, h = R.createElement;
  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(" "); }

  var STATUS = {
    /* The six states of an action (action.state); approved/executed are the kernel's names for waiting/done. */
    pending_approval: ["warning-solid", "◐", "Por aprobar"],
    waiting: ["warning", "○", "Esperando"],
    in_progress: ["info", "▶", "En proceso"],
    done: ["success", "●", "Finalizada"],
    rejected: ["neutral", "✕", "Rechazada"],
    failed: ["critical", "!", "Fallida"],
    approved: ["warning", "○", "Esperando"],
    executed: ["success", "●", "Finalizada"],
    available: ["success", "●", "Disponible"],
    busy: ["warning", "◐", "Ocupado"],
    unreachable: ["critical", "✕", "Sin contacto"],
    active: ["critical", "●", "Activa"],
    contained: ["info", "○", "Contenida"],
    closed: ["neutral", "■", "Cerrada"],
    high: ["success", "▲", "Fiabilidad alta"],
    medium: ["warning", "◆", "Fiabilidad media"],
    low: ["critical", "▼", "Fiabilidad baja"],
    real_voice: ["agent", "☎", "Llamada real"],
    real_sms: ["agent", "✉", "SMS real"],
    real_email: ["agent", "@", "Email real"]
  };
  var KIND = { information_source: "Fuente", authority: "Autoridad", responder: "Respuesta", population: "Población" };
  var MODALITY = { text: "Mensaje", call_transcript: "Llamada 112", sensor_reading: "Sensor", broadcast: "Medio" };
  var CHANNEL = { voice: "Voz", email: "Email", sms: "SMS", none: "Sin canal" };
  var TREND = { rising: ["↑", "Subiendo"], stable: ["→", "Estable"], falling: ["↓", "Bajando"] };

  function Button(p) {
    var v = p.variant || "primary", rest = Object.assign({}, p);
    ["variant", "size", "block", "className", "children"].forEach(function (k) { delete rest[k]; });
    return h("button", Object.assign({ type: "button" }, rest, {
      className: cx("vt-btn", "vt-btn--" + v, p.size === "sm" && "vt-btn--sm", p.block && "vt-btn--block", p.className)
    }), p.children);
  }

  function StatusBadge(p) {
    var s = STATUS[p.status] || [p.tone || "neutral", p.glyph || "○", p.status || ""];
    var tone = p.tone || s[0];
    return h("span", { className: cx("vt-badge", "vt-badge--" + tone) },
      h("span", { className: "vt-badge__glyph", "aria-hidden": "true" }, p.glyph || s[1]),
      p.children || p.label || s[2]);
  }

  function SeverityMeter(p) {
    var v = Math.max(0, Math.min(10, p.value || 0));
    var lvl = v >= 7 ? "high" : v >= 4 ? "mid" : "low";
    var bars = [];
    for (var i = 1; i <= 10; i++) bars.push(h("span", { key: i, className: cx("vt-sev__bar", i <= v && "is-on", "lvl-" + lvl) }));
    var t = p.trend && TREND[p.trend];
    return h("span", { className: "vt-sev", role: "img", "aria-label": "Severidad " + v + " de 10" + (t ? ", " + t[1] : "") },
      h("span", { className: "vt-sev__bars" }, bars),
      h("span", { className: "vt-sev__num" }, v),
      t && h("span", { className: cx("vt-sev__trend", "is-" + p.trend) }, t[0] + " " + t[1]));
  }

  function TextField(p) {
    return h("label", { className: cx("vt-field", p.error && "is-error") },
      p.label && h("span", { className: "vt-label" }, p.label),
      h("input", { value: p.value, defaultValue: p.defaultValue, placeholder: p.placeholder, onChange: p.onChange, className: p.mono ? "is-mono" : undefined, "aria-invalid": p.error ? "true" : undefined }),
      (p.error || p.hint) && h("span", { className: "vt-field__hint" }, p.error || p.hint));
  }

  function CrisisGate(p) {
    var st = R.useState(p.defaultCode || ""), code = st[0], setCode = st[1];
    return h("div", { className: "vt-gate" },
      h("div", { className: "vt-card vt-gate__pane" },
        h("h2", { className: "vt-gate__title" }, "Unirse a una crisis"),
        h("p", { className: "vt-gate__copy" }, "Introduce el código que te ha dado el coordinador."),
        h(TextField, { label: "Código", mono: true, placeholder: "VLC-4821", value: code, onChange: function (e) { setCode(e.target.value); }, error: p.error }),
        h(Button, { block: true, variant: "secondary", disabled: !code, onClick: function () { p.onJoin && p.onJoin(code); } }, "Unirse")),
      h("div", { className: "vt-card vt-gate__pane vt-gate__pane--dark" },
        h("h2", { className: "vt-gate__title" }, "Crear una crisis"),
        h("p", { className: "vt-gate__copy" }, "Elige el escenario y la zona. El agente empieza a escuchar señales al instante."),
        h("div", { style: { flex: 1 } }),
        h(Button, { block: true, onClick: p.onCreate }, "Crear crisis")));
  }

  function CrisisCard(p) {
    return h("button", { type: "button", className: cx("vt-card", "vt-card--select", p.selected && "is-selected"), onClick: p.onSelect, "aria-pressed": !!p.selected },
      h("div", { className: "vt-card__head" },
        h("div", null,
          h("div", { className: "vt-label" }, p.hazard),
          h("h3", { className: "vt-card__title" }, p.name)),
        h(StatusBadge, { status: p.status || "active" })),
      h(SeverityMeter, { value: p.severity, trend: p.trend }),
      h("div", { className: "vt-card__foot" },
        h("span", { className: "vt-card__meta" }, h("span", null, p.zone), h("span", { className: "vt-mono" }, p.startedAt), h("span", null, p.operators + " operadores")),
        h("span", { className: "vt-mono vt-muted" }, p.code)));
  }

  function EntityCard(p) {
    var e = p.entity || {};
    var ch = e.channel || {};
    return h("button", { type: "button", className: cx("vt-card", "vt-card--select", p.selected && "is-selected"), onClick: p.onSelect, "aria-pressed": !!p.selected },
      h("div", { className: "vt-card__head" },
        h("div", null,
          h("div", { className: "vt-label" }, KIND[e.kind] || e.kind, e.provenance === "discovered" ? " · Descubierta" : ""),
          h("h3", { className: "vt-card__title" }, e.name)),
        h(StatusBadge, { status: e.status })),
      h("dl", { className: "vt-kv" },
        h("dt", null, "Peso"), h("dd", { className: "vt-mono" }, e.weight + "/10"),
        h("dt", null, "Fiabilidad"), h("dd", null, h(StatusBadge, { status: e.trust })),
        h("dt", null, "Jurisdicción"), h("dd", null, (e.jurisdiction && e.jurisdiction.length) ? e.jurisdiction.join(", ") : "Global"),
        h("dt", null, "Canal"), h("dd", null, (CHANNEL[ch.kind] || "—") + (ch.address ? " · " : ""), ch.address && h("span", { className: "vt-mono" }, ch.address))),
      e.units && h(ResourceMeter, { label: "Unidades", available: e.units.available, total: e.units.total }));
  }

  function ResourceMeter(p) {
    var pct = p.total ? Math.round(100 * p.available / p.total) : 0;
    var low = pct <= (p.lowAt == null ? 20 : p.lowAt);
    return h("div", { className: cx("vt-res", low && "is-low") },
      h("div", { className: "vt-res__top" },
        h("span", { className: "vt-label" }, p.label),
        h("span", { className: "vt-res__state vt-mono" }, low ? "▼ Escaso" : pct + "% libre")),
      h("span", { className: "vt-res__num" }, p.available, h("small", null, " / " + p.total + (p.unit ? " " + p.unit : ""))),
      h("div", { className: "vt-res__track", role: "progressbar", "aria-valuenow": p.available, "aria-valuemin": 0, "aria-valuemax": p.total, "aria-label": p.label },
        h("div", { className: "vt-res__fill", style: { width: pct + "%" } })));
  }

  function ActionItem(p) {
    var a = p.action || {};
    var ri = a.real_interaction;
    return h("article", { className: "vt-log" },
      h("div", { className: "vt-log__head" },
        h("span", { className: "vt-mono vt-muted" }, a.id + " · " + (p.time || "")),
        h("h4", { className: "vt-log__verb" }, p.verbLabel || a.verb),
        h("span", { className: "vt-muted" }, "→ " + (p.actorName || a.actor)),
        h("span", { className: "vt-log__spacer" }),
        ri && h(StatusBadge, { status: "real_" + ri.kind }),
        h(StatusBadge, { status: a.status })),
      a.target_zones && a.target_zones.length ? h("div", { className: "vt-card__meta" }, "Zonas: " + a.target_zones.join(", ")) : null,
      h("p", { className: "vt-reason" }, h("span", { className: "vt-reason__who" }, "Agente"), a.reasoning),
      h("div", { className: "vt-chips" },
        h("span", { className: "vt-label" }, "Evidencia"),
        (a.evidence || []).map(function (id) { return h("span", { key: id, className: "vt-chip" }, id); })),
      a.status === "pending_approval" && h("div", { className: "vt-log__actions" },
        h(Button, { size: "sm", onClick: p.onApprove }, "Aprobar"),
        h(Button, { size: "sm", variant: "secondary", onClick: p.onReject }, "Rechazar"),
        p.deadline && h("span", { className: "vt-mono vt-muted", style: { alignSelf: "center" } }, "Escala en " + p.deadline)));
  }

  function SignalItem(p) {
    var s = p.signal || {};
    var loc = s.location || {};
    var noise = p.noise;
    return h("article", { className: "vt-log" },
      h("div", { className: "vt-log__head" },
        h("span", { className: "vt-mono vt-muted" }, s.id + " · " + (p.time || "")),
        h("span", { className: "vt-label" }, MODALITY[s.modality] || s.modality),
        h("span", null, p.sourceName || s.source),
        h("span", { className: "vt-log__spacer" }),
        noise ? h(StatusBadge, { tone: "neutral", glyph: "–", label: "Ruido descartado" })
          : s.confidence && h(StatusBadge, { status: s.confidence })),
      h("p", { className: cx("vt-signal__content", noise && "is-noise") }, s.content),
      h("div", { className: "vt-chips" },
        h("span", { className: "vt-chip" }, "⌖ " + (loc.precision || "unknown")),
        loc.zone && h("span", { className: "vt-chip" }, loc.zone),
        loc.text && h("span", { className: "vt-card__meta" }, loc.text)));
  }

  window.Valte = Object.assign(window.Valte || {}, {
    Button: Button, StatusBadge: StatusBadge, SeverityMeter: SeverityMeter, TextField: TextField,
    CrisisGate: CrisisGate, CrisisCard: CrisisCard, EntityCard: EntityCard, ResourceMeter: ResourceMeter,
    ActionItem: ActionItem, SignalItem: SignalItem
  });
})();
