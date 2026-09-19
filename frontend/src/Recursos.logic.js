class Component extends DCLogic {
  componentDidMount() {
    ValteLive.bind(this, cid => Promise.all([ValteLive.crisis(cid), ValteLive.get(ValteLive.asViewer(`/crises/${cid}/resources`))])
      .then(([header, resources]) => ({ header, resources })));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    const d = (this.state || {}).data || {}, r = d.resources || { units: [], requested: [], supplies: [], totals: { available: 0, total: 0 } };
    const ume = r.units.find(u => u.id === 'ume');
    const scope = r.scope || { all: true }, who = scope.all ? '' : scope.name;
    return Object.assign(ValteLive.header(this, 'Recursos'), {
      // Inventories are per entity: coordination sees them all, everyone else only their own.
      unitsCount: `${r.totals.available} libres de ${r.totals.total}` + (who ? ` · solo ${who}` : ' · todas las entidades'),
      noUnits: !!d.header && !r.units.length, noUnitsText: `${who || 'Esta entidad'} no tiene unidades propias. Las de otras entidades solo las ven ellas y el CECOPI.`,
      noSupplies: !!d.header && !r.supplies.length, noSuppliesText: `${who || 'Esta entidad'} no tiene suministros propios.`,
      requestedLabel: scope.all || r.requested.length ? 'Solicitados' : '',
      units: r.units.map(u => {
        const pct = u.total ? Math.round(100 * u.available / u.total) : 0;
        const where = u.deployed.length ? u.deployed.map(p => `${p.zone} (${p.units})`).join(', ') : u.zones.slice(0, 3).join(', ') + (u.zones.length > 3 ? '…' : '');
        return { name: u.name, kind: u.kind, free: `${u.available} / ${u.total}`, pct, barCls: 'bar' + (pct <= 20 ? ' low' : ''),
          where: where || 'Global', activation: u.arrives ? `llega ${u.arrives}` : `${u.activation_min} min`, status: u.status };
      }),
      requested: r.requested.map(q => ({ id: q.action.id, status: q.action.status, title: ume ? ume.name : q.verbLabel,
        eta: ume && ume.arrives ? `operativa a las ${ume.arrives}` : q.action.status === 'executed' ? 'en camino' : `~${ume ? Math.round(ume.activation_min / 60) : 3} h desde la aprobación` })),
      noRequested: !!d.header && scope.all && !r.requested.length,
      supplies: r.supplies.map(x => ({ label: scope.all ? `${x.name} · ${x.owner_name}` : x.name, available: x.available, total: x.total, unit: x.unit })),
      suppliesCount: `${r.supplies.length} tipos` + (who ? ` · de ${who}` : ' · con su propietario')
    });
  }
}
