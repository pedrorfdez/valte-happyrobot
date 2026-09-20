/* Contactos = the entities we can communicate with. Every communication (the agent's or a person's)
   leaves through an entity's own channel and hangs from it here.
   It is also all the population gets of the dashboard: who answers for their town, and the incident channel
   (no messages through the agent, no transcripts; what they report comes in with low reliability). */
class Component extends DCLogic {
  componentDidMount() {
    const e = new URLSearchParams(location.search).get('e');
    if (e) this.setState({ sel: e });
    ValteLive.bind(this, cid => Promise.all([ValteLive.crisis(cid), ValteLive.get(ValteLive.asViewer(`/crises/${cid}/directory`))])
      .then(([header, directory]) => ({ header, directory })));
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    const self = this, st = this.state || {}, d = st.data || {}, cid = ValteLive.crisisId(), filter = st.filter || 'all';
    const dir = d.directory || { contacts: [], counts: {} }, all = dir.contacts, c = dir.counts;
    const acc = (d.header || {}).access || {}, viewer = (d.header || {}).viewer, civil = acc.role === 'civilian';
    const me = civil && viewer ? { id: viewer.entity_id, name: viewer.name, role: 'civilian' } : {};
    const kindOf = x => civil ? x.kind_label : `${x.kind_label} · peso ${x.weight}`;  // how much an entity weighs is the kernel's business
    const COMM = { in_progress: ['agent', '●', 'En curso'], ringing: ['warning-solid', '◐', 'Llamando'], delivered: ['info', '✓', 'Entregado'],
      completed: ['success', '✓', 'Completada'], no_answer: ['critical', '✕', 'Sin respuesta'], failed: ['critical', '!', 'Fallido'],
      queued: ['neutral', '○', 'En cola'], sending: ['neutral', '○', 'Enviando'], superseded: ['neutral', '–', 'Resuelto por otra vía'] };
    const ENT = { available: ['success', '●', 'Disponible'], busy: ['warning', '◐', 'Ocupado'], unreachable: ['critical', '✕', 'Sin contacto'] };
    const badge = (map, key, extra) => { const [tone, glyph, label] = map[key] || ['neutral', '○', key]; return { tone, glyph, label: label + (extra || '') }; };
    const channel = kind => ({ tone: 'agent', glyph: kind === 'voice' ? '☎' : '@', label: kind === 'voice' ? 'Voz' : 'Email' });
    const commChannel = k => k.simulated ? { tone: 'neutral', glyph: k.channel === 'voice' ? '☎' : '@', label: (k.channel === 'voice' ? 'Voz' : 'Email') + ' · simulado' }
      : { tone: 'agent', glyph: k.channel === 'voice' ? '☎' : '@', label: k.channel === 'voice' ? 'Llamada real' : 'Email real' };
    const PURPOSE = { approval: 'Aprobación de', order: 'Orden:', notify: 'Aviso:' };

    const TABS = [['all', 'Todos', c.all], ['authority', 'Autoridades', c.authority], ['responder', 'Respuesta', c.responder], ['unreachable', 'Sin contacto', c.unreachable]];
    const rows = all.filter(e => filter === 'all' || (filter === 'unreachable' ? e.status === 'unreachable' : e.kind === filter));
    // Default selection: whoever is on the line, else the first of the list.
    const selId = st.sel || (all.find(e => e.comms.live) || all[0] || {}).id, e = all.find(x => x.id === selId);

    const comm = k => {
      const b = k.brief || {}, lines = (k.transcript || []).map(l => ({ who: l.who === 'Agente' ? 'Agente' : k.entity_name, text: l.text,
        cls: 'tline ' + (l.who === 'Agente' ? 'agent' : 'person') }));
      const out = [k.outcome && k.outcome.decision && `decisión: ${k.outcome.decision}`, k.outcome && k.outcome.hr_decision && `HappyRobot: ${k.outcome.hr_decision}`,
        k.outcome && k.outcome.summary, k.outcome && k.outcome.note, k.error].filter(Boolean).join(' · ');
      const direct = !k.action_id;
      return { time: k.time, ch: commChannel(k), st: badge(COMM, k.status), duration: k.channel === 'voice' ? k.duration : '',
        purpose: direct ? `Mensaje directo de ${b.from || 'operador'}:` : PURPOSE[k.purpose] || k.purpose, action: k.action_id || '',
        verb: direct ? b.ask || '' : '· ' + (b.verb_label || ''), entity: k.entity_name,
        hasEvidence: (b.evidence || []).length > 0, evidence: (b.evidence || []).map(x => x.split(' · ')[0]).join(' · '),
        hasOutcome: !!out, outcome: out, lines, noLines: !lines.length,
        waiting: k.status === 'ringing' ? 'Sonando… quien haga de ' + k.entity_name + ' puede atender desde aquí.' : k.status === 'in_progress' ? 'Esperando a que alguien hable…' : 'Sin contenido registrado.',
        ringing: k.status === 'ringing' && k.channel === 'voice', live: k.status === 'in_progress' && k.channel === 'voice',
        answer: () => ValteLive.voice.answer(cid, k, self), takeover: () => ValteLive.voice.listen(cid, k.id, true),
        listen: () => ValteLive.voice.listen(cid, k.id, false), hangup: () => ValteLive.voice.hangup(cid, k.id, self) };
    };

    const send = ev => {
      if (ev && ev.preventDefault) ev.preventDefault();
      const text = (st.msg || '').trim();
      if (!text || !e || st.sending) return;
      self.setState({ sending: true });
      ValteLive.post(`/crises/${cid}/entities/${e.id}/contact`, { message: text, by: (viewer || {}).entity_id || localStorage.getItem('valte.actingAs') || 'operador-cecopi' })
        .then(() => { ValteLive.toast((e.channel.kind === 'voice' ? 'Llamando a ' : 'Email en camino a ') + e.name, 'ok'); self.setState({ msg: '', sending: false }); ValteLive.reload(self); })
        .catch(err => { ValteLive.toast(err.message, 'bad'); self.setState({ sending: false }); });
    };

    return Object.assign(ValteLive.header(this, 'Contactos'), ValteLive.reportVals(this, cid, me), {
      yes: true, msg: st.msg || '', setMsg: ev => self.setState({ msg: ev.target.value }),
      civil, canContact: !!d.header && acc.can_contact !== false, canReport: civil && !!acc.can_report,
      dirTitle: civil ? 'A quién acudir' : 'Directorio',
      dirCount: civil ? `${c.all || 0} entidades que responden por ${(dir.scope.zones || []).join(', ') || 'tu zona'}` : `${c.all || 0} entidades · ${c.communications || 0} comunicaciones`,
      tabs: TABS.map(([id, label, n]) => ({ label: `${label} · ${n || 0}`, cls: 'tab vl-tab' + (filter === id ? ' is-on' : ''),
        sel: filter === id ? 'true' : 'false', pick: () => self.setState({ filter: id }) })),
      rows: rows.map(x => ({ name: x.name, kind: kindOf(x), ch: channel(x.channel.kind), address: x.channel.address || '—',
        st: x.comms.live ? badge(COMM, x.comms.live) : badge(ENT, x.status), n: x.comms.total || '—', last: x.comms.last || '—',
        cls: 'trow' + (x.id === selId ? ' is-on' : ''), pick: () => self.setState({ sel: x.id, msg: '' }) })),
      noRows: !!d.header && !rows.length, hasSel: !!e, noSel: !!d.header && !e,
      selCount: !e || civil ? '' : (e.comms.live === 'in_progress' ? 'llamada en curso' : e.comms.live === 'ringing' ? 'está sonando' : `${e.comms.total} comunicaciones`),
      sel: e ? { kind: kindOf(e), name: e.name, address: `${e.channel.address || '—'} · ${e.channel.kind === 'voice' ? 'voz' : 'email'}`,
        st: badge(ENT, e.status), zones: e.zones.length ? e.zones.join(', ') : 'Global', can: e.can.length ? e.can.join(' · ') : '—',
        escalates: e.escalates_to_name || 'nadie más en la cadena',
        sendLabel: e.channel.kind === 'voice' ? 'Nueva comunicación · llamada del agente' : 'Nueva comunicación · email',
        sendVerb: st.sending ? 'Enviando…' : e.channel.kind === 'voice' ? 'Llamar' : 'Enviar', send,
        commsLabel: `Comunicaciones · ${e.comms.total}` + (e.comms.unanswered ? ` · ${e.comms.unanswered} sin respuesta` : ''),
        comms: e.communications.map(comm), noComms: !e.communications.length } : {}
    });
  }
}
