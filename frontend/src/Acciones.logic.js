class Component extends DCLogic {
  componentDidMount() {
    const ZONE = new URLSearchParams(location.search).get('zone');
    ValteLive.bind(this, cid => Promise.all([ValteLive.crisis(cid), ValteLive.get(`/crises/${cid}/actions` + (ZONE ? `?zone=${ZONE}` : '')),
      ValteLive.get(`/crises/${cid}/zones`)]).then(([header, actions, zones]) => ({ header, actions, zones: zones.zones })));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    const ZONE = new URLSearchParams(location.search).get('zone');
    const self = this, st = this.state || {}, d = st.data || {}, cid = ValteLive.crisisId();
    const a = d.actions || { pending: [], log: [], counts: {} }, c = a.counts || {}, filter = st.filter || 'all';
    const zoneName = Object.fromEntries((d.zones || []).map(z => [z.id, z.name]));
    const TABS = [['all', 'Todas', c.all], ['pending_approval', 'Por aprobar', c.pending_approval], ['waiting', 'Esperando', c.waiting],
      ['in_progress', 'En proceso', c.in_progress], ['done', 'Finalizadas', c.done], ['failed', 'Fallidas', c.failed], ['rejected', 'Rechazadas', c.rejected]];
    const log = a.log.filter(x => filter === 'all' || x.action.state === filter);
    const selected = a.log.filter(x => x.action.id === st.sel);
    return Object.assign(ValteLive.header(this, 'Acciones'), {
      acts: ValteLive.actionRows(this, cid, a.pending, 'operador-cecopi'), noActs: !!d.header && !a.pending.length,
      pendingCount: `${a.pending.length} · esperan a un humano`, logCount: `${c.all || 0} · lo más reciente arriba`,
      tabs: ValteLive.zoneChip(ZONE, 'Acciones').concat(TABS.map(([id, label, n]) => ({ label: `${label} · ${n || 0}`, cls: 'tab vl-tab' + (filter === id ? ' is-on' : ''),
        sel: filter === id ? 'true' : 'false', pick: () => self.setState({ filter: id }) }))),
      rows: log.map(x => {
        const ri = x.action.real_interaction;
        return { time: x.time, id: x.action.id, label: x.verbLabel, actor: x.actorName, status: x.action.state,
          zones: (x.action.target_zones || []).map(z => zoneName[z] || z).join(', ') || '—',
          real: !!ri, noReal: !ri, realStatus: ri ? 'real_' + ri.kind : '',
          cls: 'trow' + (st.sel === x.action.id ? ' is-on' : ''), pick: () => self.setState({ sel: st.sel === x.action.id ? null : x.action.id }) };
      }),
      noRows: !!d.header && !log.length,
      hasSel: selected.length > 0, selList: ValteLive.actionRows(this, cid, selected, 'operador-cecopi')
    });
  }
}
