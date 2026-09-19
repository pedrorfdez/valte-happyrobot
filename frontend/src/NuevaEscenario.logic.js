class Component extends DCLogic {
  componentDidMount() {
    const self = this;
    // The flood scenario comes with the official plan (zones, entities, resources): prefill it, everything stays editable.
    Promise.all([ValteLive.get('/packs/riada-paiporta'), ValteLive.get('/meta')]).then(([pack, meta]) => {
      const names = Object.fromEntries(pack.zones.map(z => [z.id, z.name]));
      self.setState({
        pack, meta, cName: pack.name, cRegion: pack.region,
        zones: pack.zones.map(z => ({ id: z.id, name: z.name, population: z.population, origin: !!z.is_origin,
          to: (z.downstream || []).map(e => ({ name: names[e.to] || e.to, delay: e.delay_min })) })),
        srcs: pack.entities.filter(e => e.kind === 'information_source').map(e => ({ id: e.id, name: e.name, desc: e.notes || '', link: '', trust: e.trust })),
        res: pack.resources.map(r => ({ name: r.name, qty: String(r.total), unit: r.unit || '', desc: '' }))
      });
    }).catch(e => ValteLive.toast('Sin conexión con el backend: ' + e.message, 'bad'));
  }

  renderVals() {
    const self = this, st = this.state || {};
    const SCEN = [['flood', 'Inundación'], ['fire', 'Incendio forestal'], ['blackout', 'Apagón'], ['infra', 'Fallo de infraestructura'], ['mci', 'Víctimas múltiples'], ['other', 'Otro']];
    const init = Number(new URLSearchParams(location.search).get('step')) || 1, step = st.step || init, scen = st.scen || 'flood';
    const names = ['Escenario', 'Zonas', 'Fuentes de datos', 'Recursos disponibles'];
    const zones = st.zones || [], srcs = st.srcs || [], res = st.res || [];
    const fTrust = st.fTrust || 'high', nOrig = zones.filter(z => z.origin).length;
    const sums = [`${SCEN.find(s => s[0] === scen)[1]} · ${st.cName || 'sin nombre'}`, `${zones.length} zonas · ${nOrig} ${nOrig === 1 ? 'origen' : 'orígenes'}`,
      srcs.length ? `${srcs.length} ${srcs.length === 1 ? 'fuente' : 'fuentes'}` : 'Sin fuentes', res.length ? `${res.length} ${res.length === 1 ? 'recurso' : 'recursos'}` : 'Sin recursos'];
    const go = n => () => self.setState({ step: n }), set = k => e => self.setState({ [k]: e.target.value });
    const fmt = n => String(n || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    const vals = {};
    SCEN.forEach(([id]) => { const on = id === scen; vals['sc_' + id] = { on: String(on), cls: 'scn' + (on ? ' is-on' : ''), pick: () => self.setState({ scen: id }) }; });
    ['high', 'medium', 'low'].forEach(k => { const on = fTrust === k; vals['tr_' + k] = { on: String(on), cls: on ? 'is-on' : '', pick: () => self.setState({ fTrust: k }) }; });
    const ready = (st.meta && Object.keys(st.meta.workflows || {}).length) || 0;

    const create = () => {
      if (st.creating) return;
      if (!zones.length) { ValteLive.toast('Añade al menos una zona', 'warn'); self.setState({ step: 2 }); return; }
      self.setState({ creating: true });
      ValteLive.post('/crises', {
        name: st.cName, region: st.cRegion, scenario: scen, pack: scen === 'flood' ? 'riada-paiporta' : null,
        zones: zones.map(z => ({ id: z.id, name: z.name, population: z.population, is_origin: z.origin, to: z.to.map(t => `${t.name} · ${t.delay} min`) })),
        sources: srcs, resources: res.map(r => ({ name: r.name, qty: r.qty, unit: r.unit, desc: r.desc })),
        external_feed: true, start: true   // the data comes from the "Mundo exterior" app
      }).then(c => { location.href = 'PanelCoordinacion.dc.html?c=' + c.id; })
        .catch(e => { ValteLive.toast(e.message, 'bad'); self.setState({ creating: false }); });
    };

    return Object.assign(vals, {
      is1: step === 1, is2: step === 2, is3: step === 3, is4: step === 4, curNum: '0' + step, curName: names[step - 1],
      canBack: step > 1, isLast: step === 4, notLast: step < 4, back: go(Math.max(1, step - 1)), next: go(Math.min(4, step + 1)),
      steps: names.map((n, i) => { const k = i + 1, done = k < step, on = k === step;
        return { num: '0' + k, name: n, go: go(k), current: on ? 'step' : 'false', cls: 'stp' + (on ? ' is-on' : '') + (done ? ' is-done' : ''), mark: done ? '✓' : '', sum: done ? sums[i] : '' }; }),
      cName: st.cName || '', cRegion: st.cRegion || '', setCName: set('cName'), setCRegion: set('cRegion'),
      create, createLabel: st.creating ? 'Iniciando…' : 'Iniciar catástrofe',

      zNew: st.zNew || '', setZNew: set('zNew'),
      addZone: () => { const [name, pop] = (st.zNew || '').split('·').map(x => x.trim()); if (!name) return;
        self.setState({ zones: zones.concat([{ name, population: parseInt((pop || '0').replace(/\D/g, ''), 10) || 0, origin: false, to: [] }]), zNew: '' }); },
      zones: zones.map((z, i) => ({ name: z.name, hab: fmt(z.population), origin: String(z.origin), to: z.to.map(t => `${t.name} · ${t.delay} min`),
        togCls: 'tog' + (z.origin ? ' is-on' : ''), togLabel: z.origin ? '● Origen' : 'Origen',
        toggle: () => self.setState({ zones: zones.map((x, j) => j === i ? Object.assign({}, x, { origin: !x.origin }) : x) }),
        remove: () => self.setState({ zones: zones.filter((_, j) => j !== i).map(x => Object.assign({}, x, { to: x.to.filter(t => t.name !== z.name) })) }),
        connect: () => { const ans = prompt(`¿A qué zona propaga ${z.name} y en cuántos minutos?\nEjemplo: Picanya · 20`, ''); if (!ans) return;
          const [name, delay] = ans.split('·').map(x => x.trim()); const target = zones.find(x => x.name.toLowerCase() === (name || '').toLowerCase());
          if (!target || target === z) { ValteLive.toast('Esa zona no está en la lista', 'warn'); return; }
          self.setState({ zones: zones.map((x, j) => j === i ? Object.assign({}, x, { to: x.to.filter(t => t.name !== target.name).concat([{ name: target.name, delay: parseInt(delay, 10) || 30 }]) }) : x) }); } })),

      fName: st.fName || '', fDesc: st.fDesc || '', fLink: st.fLink || '', setName: set('fName'), setDesc: set('fDesc'), setLink: set('fLink'),
      addSource: e => { if (e && e.preventDefault) e.preventDefault(); if (!(st.fName || '').trim()) return;
        self.setState({ srcs: srcs.concat([{ name: st.fName.trim(), desc: (st.fDesc || '').trim(), link: (st.fLink || '').trim(), trust: fTrust }]), fName: '', fDesc: '', fLink: '' }); },
      fuentes: srcs.map((f, i) => ({ name: f.name, desc: f.desc || '—', link: f.link, hasLink: !!f.link, noLink: !f.link, trust: f.trust,
        remove: () => self.setState({ srcs: srcs.filter((_, j) => j !== i) }) })),
      noSources: srcs.length === 0,
      ingestName: ready ? 'PedroD-ingest-calls · -social · -news · PedroD-crisis-intake' : 'workflows sin aprovisionar: percepción local de respaldo',
      ingestTone: ready ? 'agent' : 'warning', ingestLabel: ready ? 'HappyRobot escucha todas las fuentes' : 'Sin HappyRobot',

      rName: st.rName || '', rQty: st.rQty || '', rUnit: st.rUnit || '', rDesc: st.rDesc || '',
      setRName: set('rName'), setRQty: set('rQty'), setRUnit: set('rUnit'), setRDesc: set('rDesc'),
      addRes: e => { if (e && e.preventDefault) e.preventDefault(); if (!(st.rName || '').trim()) return;
        self.setState({ res: res.concat([{ name: st.rName.trim(), qty: String(st.rQty || '').trim(), unit: (st.rUnit || '').trim(), desc: (st.rDesc || '').trim() }]), rName: '', rQty: '', rUnit: '', rDesc: '' }); },
      recursos: res.map((r, i) => ({ name: r.name, qty: r.qty || '—', unit: r.unit, desc: r.desc || '—', remove: () => self.setState({ res: res.filter((_, j) => j !== i) }) })),
      noRes: res.length === 0
    });
  }
}
