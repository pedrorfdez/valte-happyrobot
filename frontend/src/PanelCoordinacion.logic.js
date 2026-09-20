class Component extends DCLogic {
  componentDidMount() {
    const self = this;
    if (new URLSearchParams(location.search).get('plan')) this.setState({ planOpen: true });
    // The "how the system thinks" dialog needs three more calls: only pay for them while it is open.
    ValteLive.bind(this, cid => ValteLive.get(`/crises/${cid}/overview?role=coordination`).then(o =>
      !(self.state || {}).planOpen ? o : Promise.all([ValteLive.get(`/crises/${cid}/plan`), ValteLive.get(`/crises/${cid}/tripwires`),
        ValteLive.get(`/crises/${cid}/lessons`)]).then(([plan, tripwires, lessons]) => Object.assign(o, { think: { plan, tripwires, lessons } }))));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  think(d) {
    const self = this;
    const t = d.think || { plan: { plan: null, history: [], incidents: [] }, tripwires: [], lessons: { now: [], before: [] } }, p = t.plan.plan;
    // a lesson shows what proves it and where it has already been applied in this crisis
    const lesson = l => ({ id: l.id, text: l.text, meta: l.meta + ' · ' + l.evidenceLabel,
      uses: l.usesLabel + (l.uses.length ? ': ' + l.uses.slice(0, 3).map(u => (u.note || u.ref) + ' (' + u.by + ')').join(' · ') : ''), usedCls: 'vl-sub' + (l.uses.length ? ' vl-used' : '') });
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
      lessonsNow: (t.lessons.now || []).map(lesson), noLessonsNow: !(t.lessons.now || []).length,
      lessons: (t.lessons.before || []).map(lesson), noLessons: !(t.lessons.before || []).length,
      teach: () => { const text = prompt('Dile al sistema algo que no puede saber (p. ej. «el puente de la CV-36 está en obras: entrad por Picanya»).\nLos cerebros lo leen en su próxima decisión.', '');
        if (text && text.trim().length >= 8) ValteLive.post(`/crises/${d.header.id}/lessons`, { text: text.trim(), by: 'cecopi' })
          .then(() => { ValteLive.toast('Lección guardada: se aplica desde ya', 'ok'); ValteLive.reload(self); }).catch(e => ValteLive.toast(e.message, 'bad')); }
    };
  }

  renderVals() {
    const d = (this.state || {}).data || {}, cid = ValteLive.crisisId(), h = d.header || {}, k = d.kpis;
    const zones = (d.zones || []).map(ValteLive.zoneRow), acts = d.actions || [], incs = d.incidents || [];
    const plan = d.plan, note = h.situation_note || (plan && plan.summary) || '';
    const co = ValteLive.roleEntity(h, 'coordination'), me = co ? { id: co.entity_id, name: co.label, role: 'coordination' } : {};
    return Object.assign(ValteLive.header(this, 'PanelCoordinacion'), ValteLive.reportVals(this, cid, me), {
      yes: true,
      zones, zonesCount: k ? `${k.zones.total} · ${k.zones.origins} orígenes` : '',
      acts: ValteLive.actionRows(this, cid, acts, 'operador-cecopi'), noActs: !!d.header && !acts.length,
      actsCount: k ? `${k.actions.pending_approval} por aprobar · ${k.actions.total} en total` : '',
      incs: ValteLive.incidentRows(incs), noIncs: !!d.header && !incs.length,
      incCount: k ? `${k.incidents.open} abiertas · ${k.incidents.unattended} sin atender` : '',
      changes: (d.changes || []).slice(0, 4).map(g => Object.assign({}, g, { cls: 'vl-g is-' + g.tone })), hasChanges: (d.changes || []).length > 0,
      planOpen: !!(this.state || {}).planOpen, pl: this.think(d),
      openPlan: () => { this.setState({ planOpen: true }); ValteLive.reload(this); }, closePlan: () => this.setState({ planOpen: false }),
      hasNote: !!note, note,
      noteLabel: plan ? `Plan v${plan.version}${plan.invalidated_reason ? ' · invalidado: ' + (plan.invalidated_reason_es || plan.invalidated_reason) : ''}` : 'Situación'
    });
  }
}
