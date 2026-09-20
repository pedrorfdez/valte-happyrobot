class Component extends DCLogic {
  componentDidMount() {
    ValteLive.bind(this, cid => ValteLive.get(`/crises/${cid}`).then(h => {
      const me = ValteLive.roleEntity(h, 'authority');
      if (me) localStorage.setItem('valte.authority', me.entity_id);
      return ValteLive.get(`/crises/${cid}/overview?role=authority` + (me ? `&entity_id=${me.entity_id}` : ''));
    }));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    const self = this, d = (this.state || {}).data || {}, cid = ValteLive.crisisId(), me = d.entity || {}, k = d.kpis;
    const zones = (d.zones || []).map(ValteLive.zoneRow);
    // An authority with several zones (or all of them) sees the one that is worst off.
    const z = zones.slice().sort((a, b) => b.severity - a.severity || (a.eta_min ?? 999) - (b.eta_min ?? 999))[0];
    const acts = d.actions || [], incs = d.incidents || [];
    const run = verb => () => ValteLive.post(`/crises/${cid}/actions`, {
      actor: me.id, verb, target_zones: z ? [z.id] : [], by: me.id,
      reasoning: `Decisión directa de ${me.name} desde su panel.`
    }).then(a => { ValteLive.toast(`${a.id} · ${a.status === 'pending_approval' ? 'pendiente de aprobación' : 'en marcha'}`, 'ok'); ValteLive.reload(self); })
      .catch(e => ValteLive.toast(e.message, 'bad'));
    return Object.assign(ValteLive.header(this, 'PanelAutoridad', k), ValteLive.reportVals(this, cid, me, d.supplies), {
      yes: true,
      zone: z ? Object.assign({}, z, {
        scope: zones.length > 1 ? `la peor de tus ${zones.length} zonas` : 'tu jurisdicción',
        peak: z.eta_min == null ? '—' : z.eta_min, peakUnit: z.eta_min == null ? '' : 'min',
        peakColor: z.eta_min != null && z.eta_min <= 40 ? 'var(--critical)' : 'var(--ink)'
      }) : { name: me.name || '—', scope: '', severity: 0, trend: 'stable', warnTone: 'neutral', warnGlyph: '○', warnLabel: '—', hab: '—', evacuated_pct: 0, peak: '—', peakUnit: '', peakColor: 'var(--ink)' },
      caps: (d.capabilities || []).map(c => ({ label: c.label, run: run(c.verb) })),
      changes: (d.changes || []).slice(0, 3).map(g => Object.assign({}, g, { cls: 'vl-g is-' + g.tone })), hasChanges: (d.changes || []).length > 0,
      escalatesTo: d.escalates_to || 'nadie: eres el último escalón',
      acts: ValteLive.actionRows(this, cid, acts, me.id), noActs: !!d.header && !acts.length,
      actsCount: `${acts.filter(a => a.action.status === 'pending_approval').length} por aprobar`,
      incs: ValteLive.incidentRows(incs), noIncs: !!d.header && !incs.length,
      incCount: k ? `${k.incidents.open} abiertas · ${k.incidents.unattended} sin atender` : ''
    });
  }
}
