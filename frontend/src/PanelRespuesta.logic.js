class Component extends DCLogic {
  componentDidMount() {
    ValteLive.bind(this, cid => ValteLive.get(`/crises/${cid}`).then(h => {
      const me = ValteLive.roleEntity(h, 'responder');
      if (me) localStorage.setItem('valte.responder', me.entity_id);
      return ValteLive.get(`/crises/${cid}/overview?role=responder` + (me ? `&entity_id=${me.entity_id}` : ''));
    }));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    const d = (this.state || {}).data || {}, cid = ValteLive.crisisId(), me = d.entity || {}, k = d.kpis;
    const units = me.units || { available: 0, total: 0 }, acts = d.actions || [], incs = d.incidents || [];
    const names = Object.fromEntries((d.zones || []).map(z => [z.id, z.name]));
    const deployed = Object.entries(me.deployed || {}).map(([zone, n]) => ({ zone: names[zone] || zone, units: n }));
    const active = acts.filter(a => ['pending_approval', 'waiting', 'in_progress'].includes(a.action.state)).length;
    return Object.assign(ValteLive.header(this, 'PanelRespuesta', k), ValteLive.reportVals(this, cid, me, d.supplies), {
      yes: true,
      entityName: me.name || '—', uAvail: units.available, uTotal: units.total,
      deployed, noDeployed: !!d.header && !deployed.length,
      res: (d.supplies || []).map(r => ({ label: r.name, available: r.available, total: r.total, unit: r.unit })),
      acts: ValteLive.actionRows(this, cid, acts, me.id), noActs: !!d.header && !acts.length,
      actsCount: `${active} activas · ${acts.length} en total`,
      incs: ValteLive.incidentRows(incs), noIncs: !!d.header && !incs.length,
      incCount: k ? `${k.incidents.open} abiertas · ${k.incidents.unattended} sin atender` : ''
    });
  }
}
