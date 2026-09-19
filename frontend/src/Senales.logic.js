class Component extends DCLogic {
  componentDidMount() {
    const ZONE = new URLSearchParams(location.search).get('zone');
    ValteLive.bind(this, cid => Promise.all([ValteLive.crisis(cid), ValteLive.get(`/crises/${cid}/signals?limit=80` + (ZONE ? `&zone=${ZONE}` : '')),
      ValteLive.get(`/crises/${cid}/signals/stats`)]).then(([header, signals, stats]) => ({ header, signals: signals.signals, stats })));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    const ZONE = new URLSearchParams(location.search).get('zone');
    const self = this, st = this.state || {}, d = st.data || {}, filter = st.filter || 'all';
    const all = d.signals || [], stats = d.stats || { by_modality: {}, precision: {}, sources: [], total: 0, noise: 0 }, m = stats.by_modality;
    const TABS = [['all', 'Todas', stats.total], ['call_transcript', 'Llamadas 112', m.call_transcript], ['sensor_reading', 'Sensores', m.sensor_reading],
      ['broadcast', 'Medios', m.broadcast], ['text', 'Redes y mensajes', m.text], ['noise', 'Ruido', stats.noise]];
    const sigs = all.filter(s => filter === 'all' || (filter === 'noise' ? s.noise : s.signal.modality === filter && !s.noise));
    const P = [['exact', 'exact · coordenadas'], ['street', 'street · calle'], ['zone', 'zone · municipio'], ['region', 'region · comarca'], ['unknown', 'unknown · sin ubicar']];
    const max = Math.max(1, ...P.map(([k]) => stats.precision[k] || 0));
    return Object.assign(ValteLive.header(this, 'Senales'), {
      sigs, noSigs: !!d.header && !sigs.length, sigsCount: `${stats.total} · lo más reciente arriba`,
      tabs: ValteLive.zoneChip(ZONE, 'Senales').concat(TABS.map(([id, label, n]) => ({ label: `${label} · ${n || 0}`, cls: 'tab vl-tab' + (filter === id ? ' is-on' : ''),
        sel: filter === id ? 'true' : 'false', pick: () => self.setState({ filter: id }) }))),
      sources: stats.sources, sourcesCount: `${stats.sources.length} · por fiabilidad`,
      precision: P.map(([k, label]) => ({ label, n: stats.precision[k] || 0, pct: Math.round(100 * (stats.precision[k] || 0) / max) })),
      noiseLine: `${stats.noise} de ${stats.total}`, hasFallback: !!stats.fallback_perceptions, fallbackLine: `${stats.fallback_perceptions || 0} de ${stats.total}`
    });
  }
}
