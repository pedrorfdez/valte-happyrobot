class Component extends DCLogic {
  componentDidMount() {
    const self = this;
    if (new URLSearchParams(location.search).get('plan')) this.setState({ planOpen: true });
    // The "how the system thinks" dialog needs three more calls: only pay for them while it is open.
    ValteLive.bind(this, cid => ValteLive.get(`/crises/${cid}/overview?role=coordination`).then(o =>
      !(self.state || {}).planOpen ? o : Promise.all([ValteLive.get(`/crises/${cid}/plan`), ValteLive.get(`/crises/${cid}/tripwires`),
        ValteLive.get(`/crises/${cid}/lessons`)]).then(([plan, tripwires, lessons]) => Object.assign(o, { think: { plan, tripwires, lessons: lessons.lessons } }))));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  think(d) {
    const t = d.think || { plan: { plan: null, history: [], incidents: [] }, tripwires: [], lessons: [] }, p = t.plan.plan;
    const names = Object.fromEntries((d.zones || []).map(z => [z.id, z.name])), zn = ids => (ids || []).map(z => names[z] || z).join(', ');
    const prio = x => 'vl-prio ' + String(x || 'p3').toLowerCase();
    const cond = w => (w.if || {}).type === 'silence' ? `si ${w.if.source} calla ${w.if.silence_min} min`
      : `si ${(w.if || {}).source || 'cualquier fuente'} da severidad ≥ ${(w.if || {}).min_severity}` + ((w.if || {}).zone ? ` en ${names[w.if.zone] || w.if.zone}` : '');
    const then = w => (w.then || []).map(a => `${a.verb}${a.actor && a.actor !== 'auto' ? ' (' + a.actor + ')' : ''}`).join(' + ');
    const ORIGIN = { command: 'PedroD-crisis-command · HappyRobot', 'local-brain': 'cerebro local de respaldo' };
    const past = t.plan.history.filter(x => !x.active);
    return {
      kicker: p ? `${ORIGIN[p.origin] || p.origin} · ${p.objectives.length} objetivos` : 'sin plan todavía',
      title: p ? `Plan v${p.version}` + (p.invalidated_reason ? ' · invalidado' : '') : 'Plan',
      summary: p ? p.summary + (p.invalidated_reason ? ` — Invalidado: ${p.invalidated_reason_es || p.invalidated_reason}. El agente está redactando el siguiente.` : '') : 'El agente redacta el primer plan cuando una zona llega a severidad 4.',
      objectives: (p ? p.objectives : []).map(o => ({ priority: o.priority || '—', cls: prio(o.priority), text: o.objective || o.title || '',
        meta: [zn(o.zone_ids), o.suggested_verb, o.why].filter(Boolean).join(' · ') })),
      noObjectives: !p || !p.objectives.length,
      incidents: t.plan.incidents.filter(i => i.state !== 'closed').map(i => ({ priority: i.priority, cls: prio(i.priority), title: i.title || i.incident_id,
        meta: [zn(i.zone_ids), i.summary, `${(i.evidence || []).length} evidencias`].filter(Boolean).join(' · ') })),
      noIncidents: !t.plan.incidents.filter(i => i.state !== 'closed').length,
      history: past.map(x => ({ version: 'v' + x.version, why: x.invalidated_reason_es || x.invalidated_reason || 'sustituido por uno más reciente', meta: (x.summary || '').slice(0, 140) })),
      noHistory: !past.length,
      tripwires: t.tripwires.map(w => ({ glyph: w.active ? '⚡' : '✓', cls: 'vl-prio ' + (w.active ? 'p1' : 'p3'), text: `${cond(w)} → ${then(w)}`,
        meta: `${w.id} · lo armó ${w.set_by === 'plan' ? 'el plan de emergencias' : w.set_by === 'coordinator' ? 'el agente' : w.set_by}` + (w.last_fired_t ? ' · ya se disparó' : '') + (w.reason ? ' · ' + w.reason : '') })),
      noTripwires: !t.tripwires.length,
      lessons: t.lessons.filter(l => !l.from_this_crisis).map(l => ({ text: l.text, meta: l.kind.replace(/_/g, ' ') + (l.subject ? ' · ' + l.subject : '') })),
      noLessons: !t.lessons.filter(l => !l.from_this_crisis).length
    };
  }

  renderVals() {
    const d = (this.state || {}).data || {}, cid = ValteLive.crisisId(), h = d.header || {}, k = d.kpis;
    const zones = (d.zones || []).map(ValteLive.zoneRow), acts = d.actions || [], sigs = d.signals || [];
    const plan = d.plan, note = h.situation_note || (plan && plan.summary) || '';
    const co = ValteLive.roleEntity(h, 'coordination'), me = co ? { id: co.entity_id, name: co.label, role: 'coordination' } : {};
    return Object.assign(ValteLive.header(this, 'PanelCoordinacion'), ValteLive.reportVals(this, cid, me), {
      yes: true,
      zones, zonesCount: k ? `${k.zones.total} · ${k.zones.origins} orígenes` : '',
      acts: ValteLive.actionRows(this, cid, acts, 'operador-cecopi'), noActs: !!d.header && !acts.length,
      actsCount: k ? `${k.actions.pending_approval} por aprobar · ${k.actions.total} en total` : '',
      sigs, noSigs: !!d.header && !sigs.length,
      sigsCount: k ? `${k.signals.total} · ${k.signals.noise} de ruido · ${k.signals.per_min}/min` : '',
      changes: (d.changes || []).slice(0, 4).map(g => Object.assign({}, g, { cls: 'vl-g is-' + g.tone })), hasChanges: (d.changes || []).length > 0,
      planOpen: !!(this.state || {}).planOpen, pl: this.think(d),
      openPlan: () => { this.setState({ planOpen: true }); ValteLive.reload(this); }, closePlan: () => this.setState({ planOpen: false }),
      hasNote: !!note, note,
      noteLabel: plan ? `Plan v${plan.version}${plan.invalidated_reason ? ' · invalidado: ' + (plan.invalidated_reason_es || plan.invalidated_reason) : ''}` : 'Situación'
    });
  }
}
