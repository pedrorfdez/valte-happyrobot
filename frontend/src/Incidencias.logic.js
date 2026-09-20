const CONF_ES = { low: 'baja', medium: 'media', high: 'alta' };

class Component extends DCLogic {
  componentDidMount() {
    const qs = new URLSearchParams(location.search), ZONE = qs.get('zone'), OPEN = qs.get('open'), ST = qs.get('state');
    if (OPEN) this.setState({ sel: OPEN });
    if (ST) this.setState({ filter: ST });
    const self = this;
    this.__esc = e => { if (e.key === 'Escape' && (self.state || {}).sel) self.setState({ sel: null }); };
    document.addEventListener('keydown', this.__esc);
    ValteLive.bind(this, cid => Promise.all([ValteLive.crisis(cid),
      ValteLive.get(ValteLive.asViewer(`/crises/${cid}/incidents?limit=200` + (ZONE ? `&zone=${ZONE}` : '')))])
      .then(([header, incidents]) => {
        const sel = (self.state || {}).sel;
        if (!sel) return { header, incidents };
        return ValteLive.get(`/crises/${cid}/incidents/${sel}`).then(detail => ({ header, incidents, detail })).catch(() => ({ header, incidents }));
      }));
  }
  componentWillUnmount() { ValteLive.unbind(this); document.removeEventListener('keydown', this.__esc); }

  dialog(d, cid, st) {
    const self = this, det = d.detail;
    // The dialog follows the selection, not the last detail fetched: `detail` lives in `data` and only changes on the
    // next load, so closing on it alone left the ✕ (and the scrim) doing nothing.
    if (!det || !st.sel || det.id !== st.sel) return { hasSel: false, sel: {} };
    const v = ValteLive.view(), by = v.entity_id || 'cecopi';
    const all = (d.incidents && d.incidents.incidents) || [];
    function act(path, body) {
      return ValteLive.post(`/crises/${cid}/incidents/${det.id}/${path}`, body)
        .then(() => { ValteLive.toast(path === 'dismiss' ? `${det.id} descartada` : `${det.id} fusionada`, 'ok'); self.setState({ sel: null }); ValteLive.reload(self); })
        .catch(e => ValteLive.toast(e.message, 'bad'));
    }
    return {
      hasSel: true, close: () => self.setState({ sel: null }),
      sel: {
        kicker: `${det.id} · ${det.kindLabel}` + (det.zone_name ? ' · ' + det.zone_name : ''),
        title: det.title, tone: det.tone, stateLabel: det.state_label, priority: det.priority,
        prioCls: 'vl-prio ' + det.priority.toLowerCase(), evidenceLabel: det.evidenceLabel, confidenceLabel: 'confianza ' + det.confidenceLabel,
        summary: det.summary, hasNote: !!det.note, note: det.note,
        signals: (det.signal_list || []).map(s => ({ time: s.time, sourceName: s.sourceName, confidence: CONF_ES[s.signal.confidence] || s.signal.confidence || '—',
          content: s.signal.content, style: (s.noise || s.signal.is_noise) ? 'text-decoration: line-through; color: var(--ink-muted);' : '' })),
        noSignals: !(det.signal_list || []).length,
        actions: (det.action_list || []).map(a => ({ verbLabel: a.verbLabel, actorName: a.actorName, deadline: a.deadline ? 'escala en ' + a.deadline : (a.action.state || '') })),
        noActions: !(det.action_list || []).length,
        attendedByLine: det.attendedBy ? 'Atendida por ' + det.attendedBy : (det.open ? 'Nadie asignado todavía.' : (det.closed_reason || '')),
        canAct: det.open,
        dismiss: () => {
          const reason = prompt('¿Por qué se descarta ' + det.id + '?', 'Falsa alarma');
          if (reason == null) return;
          act('dismiss', { by, reason });
        },
        merge: () => {
          const cands = all.filter(i => i.open && i.id !== det.id && (!det.zone_id || i.zone_id === det.zone_id));
          if (!cands.length) { ValteLive.toast('No hay otra incidencia abierta en esta zona.', 'warn'); return; }
          const list = cands.map(i => `${i.id} — ${i.title}`).join('\n');
          const into = prompt('¿Con qué incidencia es la misma? Escribe su id.\n\n' + list, cands[0].id);
          if (!into) return;
          if (!cands.some(i => i.id === into)) { ValteLive.toast('Id no encontrado entre las abiertas de la zona.', 'bad'); return; }
          act('merge', { into, by });
        }
      }
    };
  }

  renderVals() {
    const self = this, st = this.state || {}, d = st.data || {}, cid = ValteLive.crisisId();
    const qs = new URLSearchParams(location.search), ZONE = qs.get('zone');
    const inc = d.incidents || { counts: {}, incidents: [], noise: [] }, c = inc.counts || {}, filter = st.filter || 'open';
    const closedN = (c.resolved || 0) + (c.dismissed || 0);
    const TABS = [['open', 'Abiertas', c.open], ['unattended', 'Sin atender', c.unattended], ['candidate', 'Sin confirmar', c.candidate],
      ['attended', 'Atendidas', c.attended], ['closed', 'Cerradas', closedN]];
    const inTab = (i) => filter === 'open' ? i.open : filter === 'unattended' ? (i.state === 'candidate' || i.state === 'active')
      : filter === 'candidate' ? i.state === 'candidate' : filter === 'attended' ? i.state === 'attended'
      : filter === 'closed' ? (i.state === 'resolved' || i.state === 'dismissed') : true;
    const list = (inc.incidents || []).filter(inTab);
    const rows = list.map(i => ({
      cls: 'trow' + (st.sel === i.id ? ' is-on' : ''), open: () => { self.setState({ sel: i.id }); ValteLive.reload(self); },
      priority: i.priority, prioCls: 'vl-prio ' + (i.priority || 'p3').toLowerCase(), title: i.title, timeRange: i.time === i.lastTime ? i.time : `${i.time} → ${i.lastTime}`,
      tone: i.tone, stateLabel: i.state_label, evidenceLabel: i.evidenceLabel, confidenceLabel: i.confidenceLabel, peopleLabel: i.peopleLabel || '—',
      attention: i.waitingLabel || i.attendedBy || '—', waitColor: i.waitingLabel ? 'var(--critical)' : 'var(--ink-muted)'
    }));
    return Object.assign(ValteLive.header(this, 'Incidencias'), this.dialog(d, cid, st), {
      incCount: `${c.total || 0} · lo que nadie atiende, primero`,
      tabs: ValteLive.zoneChip(ZONE, 'Incidencias').concat(TABS.map(([id, label, n]) => ({ label: `${label} · ${n || 0}`, cls: 'tab vl-tab' + (filter === id ? ' is-on' : ''),
        sel: filter === id ? 'true' : 'false', pick: () => self.setState({ filter: id }) }))),
      rows, noRows: !!d.header && !rows.length,
      noise: (inc.noise || []).map(n => ({ time: n.time, sourceName: n.sourceName, text: n.signal.content })),
      noiseOpen: !!st.noiseOpen, toggleNoise: () => self.setState({ noiseOpen: !st.noiseOpen }),
      noiseToggleLabel: `${st.noiseOpen ? '▾' : '▸'} ${c.noise || 0} avisos descartados como ruido`
    });
  }
}
