class Component extends DCLogic {
  renderVals() {
    var self = this, st = this.state || {}, D = {"scen": [{"id": "flood", "label": "Inundación"}, {"id": "fire", "label": "Incendio forestal"}, {"id": "blackout", "label": "Apagón"}, {"id": "infra", "label": "Fallo de infraestructura"}, {"id": "mci", "label": "Víctimas múltiples"}, {"id": "other", "label": "Otro"}], "zones": [{"name": "Chiva", "hab": "15 800", "origin": true, "to": ["Cheste · 25 min", "Paiporta · 38 min"]}, {"name": "Torrent", "hab": "87 400", "origin": true, "to": ["Picanya · 50 min"]}, {"name": "Cheste", "hab": "8 900", "origin": false, "to": ["Picanya · 19 min"]}, {"name": "Paiporta", "hab": "27 180", "origin": false, "to": ["Massanassa · 17 min"]}, {"name": "Picanya", "hab": "11 700", "origin": false, "to": ["Massanassa · 11 min"]}, {"name": "Massanassa", "hab": "9 800", "origin": false, "to": []}], "fuentes": []};
    var init = this.props.initialStep ? Number(this.props.initialStep) : 1;
    var step = st.step || init;
    var scen = st.scen || 'flood';
    var origins = st.origins || D.zones.reduce(function (m, z) { m[z.name] = z.origin; return m; }, {});
    var names = ['Escenario', 'Zonas', 'Fuentes de datos', 'Recursos disponibles'];
    var scenLabel = D.scen.filter(function (s) { return s.id === scen; })[0].label;
    var nOrig = Object.keys(origins).filter(function (k) { return origins[k]; }).length;
    var srcs = st.srcs || D.fuentes;
    var fName = st.fName || '', fDesc = st.fDesc || '', fLink = st.fLink || '', fTrust = st.fTrust || 'high';
    var nConn = srcs.length;
    var res = st.res || [];
    var rName = st.rName || '', rQty = st.rQty || '', rUnit = st.rUnit || '', rDesc = st.rDesc || '';
    var sums = [scenLabel + ' · Riada en Paiporta', D.zones.length + ' zonas · ' + nOrig + (nOrig === 1 ? ' origen' : ' orígenes'), (nConn ? nConn + (nConn === 1 ? ' fuente' : ' fuentes') : 'Sin fuentes'), (res.length ? res.length + (res.length === 1 ? ' recurso' : ' recursos') : 'Sin recursos')];
    var scBtns = {};
    D.scen.forEach(function (s) { var on = s.id === scen; scBtns['sc_' + s.id] = { on: on ? 'true' : 'false', cls: 'scn' + (on ? ' is-on' : ''), pick: function () { self.setState({ scen: s.id }); } }; });
    ['high', 'medium', 'low'].forEach(function (k) { var on = fTrust === k; scBtns['tr_' + k] = { on: on ? 'true' : 'false', cls: on ? 'is-on' : '', pick: function () { self.setState({ fTrust: k }); } }; });
    var go = function (n) { return function () { self.setState({ step: n }); }; };
    return Object.assign(scBtns, {
      is1: step === 1, is2: step === 2, is3: step === 3, is4: step === 4,
      curNum: '0' + step, curName: names[step - 1],
      canBack: step > 1, isLast: step === 4, notLast: step < 4,
      back: go(Math.max(1, step - 1)), next: go(Math.min(4, step + 1)),
      steps: names.map(function (n, i) {
        var k = i + 1, done = k < step, on = k === step;
        return { num: '0' + k, name: n, go: go(k), current: on ? 'step' : 'false',
          cls: 'stp' + (on ? ' is-on' : '') + (done ? ' is-done' : ''),
          mark: done ? '✓' : '', sum: done ? sums[i] : '' };
      }),
      fuentes: srcs.map(function (f, i) {
        return { name: f.name, desc: f.desc || '—', link: f.link, hasLink: !!f.link, noLink: !f.link, trust: f.trust,
          remove: function () { self.setState({ srcs: srcs.filter(function (_, j) { return j !== i; }) }); } };
      }),
      noSources: srcs.length === 0,
      recursos: res.map(function (r, i) {
        return { name: r.name, qty: r.qty || '—', unit: r.unit, desc: r.desc || '—',
          remove: function () { self.setState({ res: res.filter(function (_, j) { return j !== i; }) }); } };
      }),
      noRes: res.length === 0,
      rName: rName, rQty: rQty, rUnit: rUnit, rDesc: rDesc,
      setRName: function (e) { self.setState({ rName: e.target.value }); },
      setRQty: function (e) { self.setState({ rQty: e.target.value }); },
      setRUnit: function (e) { self.setState({ rUnit: e.target.value }); },
      setRDesc: function (e) { self.setState({ rDesc: e.target.value }); },
      addRes: function (e) { if (e && e.preventDefault) e.preventDefault(); if (!rName.trim()) return;
        self.setState({ res: res.concat([{ name: rName.trim(), qty: String(rQty).trim(), unit: rUnit.trim(), desc: rDesc.trim() }]), rName: '', rQty: '', rUnit: '', rDesc: '' }); },
      fName: fName, fDesc: fDesc, fLink: fLink,
      setName: function (e) { self.setState({ fName: e.target.value }); },
      setDesc: function (e) { self.setState({ fDesc: e.target.value }); },
      setLink: function (e) { self.setState({ fLink: e.target.value }); },
      addSource: function (e) { if (e && e.preventDefault) e.preventDefault(); if (!fName.trim()) return;
        self.setState({ srcs: srcs.concat([{ name: fName.trim(), desc: fDesc.trim(), link: fLink.trim(), trust: fTrust }]), fName: '', fDesc: '', fLink: '' }); },
      zones: D.zones.map(function (z) {
        var o = !!origins[z.name];
        return { name: z.name, hab: z.hab, to: z.to, origin: o ? 'true' : 'false',
          togCls: 'tog' + (o ? ' is-on' : ''), togLabel: o ? '● Origen' : 'Origen',
          toggle: function () { var n = Object.assign({}, origins); n[z.name] = !o; self.setState({ origins: n }); } };
      })
    });
  }
}
