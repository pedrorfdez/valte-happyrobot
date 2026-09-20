class Component extends DCLogic {
  componentDidMount() {
    const z = new URLSearchParams(location.search).get('z');
    if (z) this.setState({ sel: z });
    const self = this, saved = localStorage.getItem('valte.zonesView');
    this.setState({ view: new URLSearchParams(location.search).get('view') || saved || 'map' });
    ValteLive.bind(this, cid => Promise.all([ValteLive.crisis(cid), ValteLive.get(ValteLive.asViewer(`/crises/${cid}/zones`)),
      ValteLive.get(ValteLive.asViewer(`/crises/${cid}/signals?precise=true&noise=false&limit=30`))])
      .then(([header, zones, signals]) => {
        // Zones typed into the wizard have no coordinates yet: ask the kernel to look them up (once); they arrive as events.
        if (!self.__located && zones.zones.some(z => !z.centroid)) { self.__located = true; ValteLive.post(`/crises/${cid}/locate`).catch(() => {}); }
        return { header, zones: zones.zones, signals: signals.signals };
      }));
    // The map library is only fetched by the screen that draws a map.
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = 'assets/vendor/leaflet.css'; document.head.appendChild(css);
    const load = src => new Promise((ok, bad) => { const el = document.createElement('script'); el.src = src; el.onload = ok; el.onerror = bad; document.head.appendChild(el); });
    load('assets/vendor/leaflet.js').then(() => load('assets/valte-map.js')).then(() => self.setState({ mapReady: true })).catch(() => self.setState({ mapFailed: true }));
  }
  componentDidUpdate() { this.syncMap(); }
  componentWillUnmount() { ValteLive.unbind(this); if (window.ValteMap) ValteMap.destroy(); }

  syncMap() {
    const st = this.state || {}, d = st.data || {};
    if (st.view !== 'map' || !st.mapReady || !window.ValteMap || !d.zones) return;
    const rows = d.zones.map(ValteLive.zoneRow).map(z => Object.assign({}, z, { cls: z.id === st.sel ? 'is-on' : '' }));
    ValteMap.sync(document.getElementById('vl-map'), rows, d.signals || [], id => this.setState({ sel: id }));
  }

  /* The canvas is a time axis: x = minutes the hazard needs to get there from an origin (19.5 px per minute,
     as in the design); rows are assigned greedily so boxes never overlap. */
  layout(zones) {
    const PX = 19.5, W = 200, H = 96, ROWS = [34, 194, 354], byId = Object.fromEntries(zones.map(z => [z.id, z]));
    const dist = {};
    zones.filter(z => z.is_origin || !z.from.length).forEach(z => { dist[z.id] = 0; });
    for (let pass = 0; pass < zones.length; pass++) {
      zones.forEach(z => z.to.forEach(e => {
        if (dist[z.id] != null && (dist[e.zone] == null || dist[z.id] + e.delay_min < dist[e.zone])) dist[e.zone] = dist[z.id] + e.delay_min;
      }));
    }
    const pos = {}, placed = [];
    zones.slice().sort((a, b) => (dist[a.id] || 0) - (dist[b.id] || 0)).forEach(z => {
      const x = Math.min(1184, Math.round((dist[z.id] || 0) * PX));
      const parents = z.from.map(f => pos[f.zone]).filter(Boolean);
      // Cheapest row: never overlap a box; avoid rows where the arrow from a parent would run behind another box.
      const cost = r => {
        if (placed.some(q => q.row === r && Math.abs(q.x - x) < W + 40)) return 1e6 + r;
        const blocked = parents.filter(p => p.row === r && placed.some(q => q.row === r && q.x > p.x && q.x < x)).length;
        const sameRowAsParent = parents.some(p => p.row === r) ? 0 : 1;
        return blocked * 10 + sameRowAsParent + r * 0.1;
      };
      const row = [0, 1, 2].reduce((best, r) => cost(r) < cost(best) ? r : best, 0);
      pos[z.id] = { x, y: ROWS[row], row };
      placed.push(pos[z.id]);
    });
    const edges = [], heads = [], labels = [];
    zones.forEach(z => z.to.forEach(e => {
      const a = pos[z.id], b = pos[e.zone];
      if (!a || !b || !byId[e.zone]) return;
      const sx = a.x + W, sy = a.y + H / 2, tx = b.x - 7, ty = b.y + H / 2, mx = Math.round((sx + tx) / 2);
      edges.push(`M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}`);
      heads.push(`M${tx},${ty - 5} L${tx + 7},${ty} L${tx},${ty + 5} Z`);
      labels.push({ text: `+${e.delay_min} min`, pos: `left: ${mx}px; top: ${Math.round((sy + ty) / 2)}px;` });
    }));
    return { pos, edgesD: edges.join(' '), headsD: heads.join(' '), edgeLabels: labels };
  }

  renderVals() {
    const self = this, st = this.state || {}, d = st.data || {}, zones = (d.zones || []).map(ValteLive.zoneRow);
    const lay = this.layout(zones);
    const view = z => Object.assign({}, z, {
      sev: z.severity, evac: z.evacuated_pct, peak: z.eta_min == null ? '—' : z.eta_min,
      origin: z.is_origin, noTo: !z.hasTo,
      actionsHref: 'Acciones.dc.html?zone=' + z.id, signalsHref: 'Incidencias.dc.html?zone=' + z.id,
      pos: `left: ${lay.pos[z.id].x}px; top: ${lay.pos[z.id].y}px;`,
      cls: 'zn' + (z.is_origin ? ' is-origin' : '') + (z.id === st.sel ? ' is-on' : ''),
      open: () => self.setState({ sel: z.id })
    });
    const list = zones.map(view), sel = list.find(z => z.id === st.sel);
    const located = zones.filter(z => z.centroid).length, onList = st.view === 'list';
    const onMap = st.view === 'map' && located > 0 && !st.mapFailed, onGraph = !onMap && !onList;
    const pickView = v => () => { localStorage.setItem('valte.zonesView', v); self.setState({ view: v }); };
    // The list reads top-left to bottom-right in the order things need attention: origins, zones already hit, then by arrival.
    const urgency = z => z.is_origin ? -2 : z.eta === 'Afectada' ? -1 : z.eta_min != null ? z.eta_min : 1e6;
    const cards = !onList ? [] : list.slice().sort((a, b) => urgency(a) - urgency(b) || b.severity - a.severity).map(z => {
      const flags = [z.road_cut ? 'acceso cortado' : '', z.power_out ? 'sin suministro eléctrico' : ''].filter(Boolean);
      return Object.assign({}, z, {
        cardCls: 'zc' + (z.is_origin ? ' is-origin' : '') + (z.id === st.sel ? ' is-on' : ''),
        cardMeta: `${z.hab} hab. · ${z.evacuated_pct} % evacuados`,
        cardFlow: z.hasTo ? '→ ' + z.to.map(e => `${e.name} ${e.d}`).join(' · ') : 'Final del recorrido',
        cardFlags: flags.join(' · '), hasFlags: flags.length > 0
      });
    });
    return Object.assign(ValteLive.header(this, 'Zonas'), {
      viewTitle: onMap ? 'Territorio' : onList ? 'Listado' : 'Propagación', mapDisplay: onMap ? 'block' : 'none',
      cardsDisplay: onList ? 'grid' : 'none', cards,
      views: [{ label: located ? 'Mapa' : 'Mapa · localizando…', cls: onMap ? 'is-on' : '', sel: String(onMap), pick: pickView('map') },
        { label: 'Tiempos de llegada', cls: onGraph ? 'is-on' : '', sel: String(onGraph), pick: pickView('graph') },
        { label: 'Lista', cls: onList ? 'is-on' : '', sel: String(onList), pick: pickView('list') }],
      zones: list, sel: sel || list[0] || {}, hasSel: !!sel, close: () => self.setState({ sel: null }),
      zonesCount: `${zones.length} zonas · ${zones.filter(z => z.is_origin).length} orígenes · pulsa una zona`,
      edgesD: lay.edgesD, headsD: lay.headsD, edgeLabels: lay.edgeLabels
    });
  }
}
