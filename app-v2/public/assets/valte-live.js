/* Valte · live data for the design's screens.
 *
 * The screens are the design export's own templates (dc-runtime + Valte.*
 * components). This file replaces their mock data with the kernel's API:
 * it loads what a screen needs, reloads it when the event stream says the
 * world changed, and wires the human interventions and the voice calls. */
(function () {
  var API = localStorage.getItem('valte.api') ||
    (location.pathname.indexOf('/app') === 0 ? location.origin : 'http://localhost:8010');
  var qs = new URLSearchParams(location.search);

  var PAGE = (location.pathname.split('/').pop() || '').replace('.dc.html', '');
  var PAGE_ROLE = { PanelCoordinacion: 'coordination', PanelAutoridad: 'authority', PanelRespuesta: 'responder' }[PAGE];
  if (PAGE_ROLE && qs.get('e')) localStorage.setItem('valte.' + PAGE_ROLE, qs.get('e'));

  if (PAGE_ROLE) localStorage.setItem('valte.viewRole', PAGE_ROLE);
  if (qs.get('as')) {  // deep link: open any screen as a given entity (?as=bomberos-vlc&asrole=responder)
    var asRole = qs.get('asrole') || 'responder';
    localStorage.setItem('valte.viewRole', asRole);
    localStorage.setItem('valte.' + asRole, qs.get('as'));
  }

  /* Inventories are per entity: screens ask for them "as" the entity whose panel you came from. */
  function view() {
    var role = localStorage.getItem('valte.viewRole') || 'coordination';
    return { role: role, entity_id: role === 'coordination' ? null : localStorage.getItem('valte.' + role) };
  }
  function asViewer(path) {
    var v = view();
    return v.entity_id ? path + (path.indexOf('?') < 0 ? '?' : '&') + 'entity_id=' + encodeURIComponent(v.entity_id) : path;
  }
  function crisis(cid) { return get(asViewer('/crises/' + cid)); }

  function crisisId() {
    var c = qs.get('c');
    if (c) localStorage.setItem('valte.crisis', c);
    return c || localStorage.getItem('valte.crisis');
  }

  /* A dashboard opened from another device (through the tunnel or the LAN) has to present the dashboard key:
     open it once with ?key=… and it is remembered. On this machine no key is needed. */
  if (qs.get('key')) localStorage.setItem('valte.key', qs.get('key'));
  var KEY = localStorage.getItem('valte.key') || '';

  function req(method, path, body) {
    var headers = body ? { 'content-type': 'application/json' } : {};
    if (KEY) headers['X-Valte-Key'] = KEY;
    return fetch(API + path, {
      method: method,
      headers: headers,
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
        return data;
      });
    });
  }
  var get = function (path) { return req('GET', path); };
  var post = function (path, body) { return req('POST', path, body || {}); };

  function toast(text, tone) {
    var el = document.createElement('div');
    el.className = 'vl-toast' + (tone ? ' is-' + tone : '');
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 4200);
  }

  /* The design is a fixed 1440x900 canvas: scale it to whatever screen the demo runs on. */
  function fit() {
    var s = Math.min(window.innerWidth / 1440, window.innerHeight / 900);
    var b = document.body.style;
    b.width = '1440px'; b.height = '900px'; b.transformOrigin = '0 0';
    b.transform = 'translate(' + Math.max(0, (window.innerWidth - 1440 * s) / 2) + 'px,' +
      Math.max(0, (window.innerHeight - 900 * s) / 2) + 'px) scale(' + s + ')';
    document.documentElement.style.overflow = 'hidden';
  }
  window.addEventListener('resize', fit);
  document.addEventListener('DOMContentLoaded', fit);

  /* Load now, and again (debounced) whenever the kernel says something changed. */
  function bind(logic, load, opts) {
    opts = opts || {};
    var cid = opts.noCrisis ? null : crisisId();
    if (!cid && !opts.noCrisis) { location.href = 'Main.dc.html'; return; }
    var busy = false, again = false, timer = null, es = null, poll = null;
    function run() {
      if (busy) { again = true; return; }
      busy = true;
      load(cid).then(function (data) { logic.setState({ data: data, error: null, loaded: true }); })
        .catch(function (e) { logic.setState({ error: String(e.message || e) }); })
        .then(function () { busy = false; if (again) { again = false; run(); } });
    }
    run();
    if (qs.get('static')) { /* one-shot render (screenshots, printing): no stream */ }
    else if (cid) {
      es = new EventSource(API + '/crises/' + cid + '/events' + (KEY ? '?key=' + encodeURIComponent(KEY) : ''));
      var onEvent = function (raw) {
        var ev; try { ev = JSON.parse(raw.data); } catch (e) { return; }
        if (ev.type === 'clock.tick') { logic.setState({ clock: ev.payload }); return; }
        if (opts.ignore && opts.ignore.test(ev.type)) return;
        clearTimeout(timer); timer = setTimeout(run, 250);
      };
      ['clock.tick', 'clock.changed', 'crisis.updated', 'crisis.started', 'crisis.closed', 'signal.created', 'signal.updated',
        'zone.updated', 'entity.updated', 'resource.updated', 'action.created', 'action.updated', 'approval.requested',
        'approval.decided', 'approval.escalated', 'approval.stalled', 'contact.created', 'contact.updated',
        'contact.transcript', 'contact.unanswered', 'tripwire.armed', 'tripwire.fired', 'plan.replaced',
        'plan.invalidated', 'brain.wake', 'brain.result', 'outcome.recorded', 'sim.event', 'hr.error', 'hr.fallback',
        'lesson.created'].forEach(function (t) { es.addEventListener(t, onEvent); });
    } else {
      poll = setInterval(run, 3000);
    }
    logic.__valte = { close: function () { if (es) es.close(); clearTimeout(timer); clearInterval(poll); }, reload: run };
  }
  function unbind(logic) { if (logic.__valte) logic.__valte.close(); }
  function reload(logic) { if (logic.__valte) logic.__valte.reload(); }

  /* ── header shared by every screen ─────────────────────────────────── */
  var TITLES = { Zonas: 'Zonas', Acciones: 'Acciones', Senales: 'Señales', Recursos: 'Recursos', Contactos: 'Contactos' };
  var PANELS = { coordination: 'PanelCoordinacion.dc.html', authority: 'PanelAutoridad.dc.html', responder: 'PanelRespuesta.dc.html' };
  var KIND = { coordination: 'Coordinación', authority: 'Autoridad', responder: 'Respuesta' };

  function roleEntity(h, role) {
    var saved = localStorage.getItem('valte.' + role);
    var options = (h.roles || []).filter(function (r) { return r.role === role; });
    var prefer = { authority: 'alcaldia-paiporta', responder: 'bomberos-vlc' }[role];
    return options.filter(function (r) { return r.entity_id === saved; })[0] ||
      options.filter(function (r) { return r.entity_id === prefer; })[0] || options[0] || null;
  }

  function header(logic, page, kpisOverride) {
    var st = logic.state || {}, d = st.data || {}, h = d.header;
    if (!h) return { hd: { title: 'Valte', sub: st.error || 'cargando…', sev: 0, trend: 'stable', segs: [], kpis: [], ringing: [], backHref: 'Main.dc.html' } };
    var clock = st.clock || h.clock, k = kpisOverride || h.kpis, isPanel = page.indexOf('Panel') === 0;
    var pace = clock.paused ? 'en pausa' : clock.slowmo ? '1× · llamada en curso' : clock.speed + '×';
    var line = h.code + ' · ' + clock.clock + ' · ' + clock.elapsed + ' · ' + pace + (h.status !== 'active' ? ' · CERRADA' : '');
    if (!isPanel && h.viewer && !h.viewer.sees_everything) line += ' · viendo como ' + h.viewer.name;
    var pageRole = { PanelCoordinacion: 'coordination', PanelAutoridad: 'authority', PanelRespuesta: 'responder' }[page];
    var segs = !isPanel ? [] : ['coordination', 'authority', 'responder'].map(function (role) {
      var e = roleEntity(h, role), href = PANELS[role];
      var options = (h.roles || []).filter(function (r) { return r.role === role; });
      if (role === pageRole && options.length > 1) {  // clicking the active segment switches to the next entity of that role
        var next = options[(options.indexOf(e) + 1) % options.length];
        href += '?e=' + next.entity_id;
      }
      return { href: href, cls: 'seg' + (role === pageRole ? ' is-on' : ''), name: e ? e.label : '—',
        kind: KIND[role] + (role === pageRole && options.length > 1 ? ' · ' + (options.indexOf(e) + 1) + '/' + options.length + ' ⟳' : '') };
    });
    function kpi(href, label, num, rest, color, first) {
      return { href: href, label: label, num: num, rest: rest, color: color,
        cls: 'kpi-link' + (href.indexOf(page + '.') === 0 ? ' is-on' : ''),
        style: 'flex-grow: 1; display: flex; flex-direction: column; gap: 4px;' + (first ? '' : ' border-left: 1px solid var(--line-strong); padding-left: 24px;') };
    }
    var me = localStorage.getItem('valte.actingAs') || '';
    return { hd: {
      title: isPanel ? h.name : TITLES[page] || h.name, sub: isPanel ? line : h.name + ' · ' + line,
      backHref: isPanel ? 'Main.dc.html' : PANELS[view().role] || 'PanelCoordinacion.dc.html',
      sev: h.severity, trend: h.trend, level: h.emergency_level > 0, levelLabel: 'Nivel ' + h.emergency_level, segs: segs,
      kpis: [
        kpi('Zonas.dc.html', 'Zonas', k.zones.warned, '/ ' + k.zones.total + ' avisadas', 'var(--ink)', true),
        kpi('Acciones.dc.html', 'Acciones', k.actions.pending_approval, 'por aprobar · ' + k.actions.total + ' en total', k.actions.pending_approval ? 'var(--warning-text)' : 'var(--ink)'),
        kpi('Senales.dc.html', 'Señales', k.signals.total, '· ' + k.signals.noise + ' de ruido · ' + k.signals.per_min + '/min', 'var(--ink)'),
        kpi('Recursos.dc.html', 'Recursos', k.units.available, '/ ' + k.units.total + ' ' + (k.units.label || 'unidades libres'), k.units.total && k.units.available / k.units.total <= 0.2 ? 'var(--critical)' : 'var(--ink)'),
        kpi('Contactos.dc.html', 'Contactos', k.contacts.entities != null ? k.contacts.entities : k.contacts.total,
          '· ' + (k.contacts.unreachable != null ? k.contacts.unreachable : k.contacts.unanswered) + ' sin respuesta',
          (k.contacts.unreachable || k.contacts.unanswered) ? 'var(--critical)' : 'var(--ink)')
      ],
      ringing: (h.ringing || []).filter(function (c) { return c.channel === 'voice'; }).map(function (c) {
        var live = c.status === 'in_progress';
        return { title: (live ? 'Llamada en curso · ' : 'Llamada entrante · ') + c.entity_name, ask: (c.brief || {}).ask || '',
          meta: (c.action_id || '') + ' · ' + c.time, entity: c.entity_name, canAnswer: !live, live: live && voice.contact === c.id,
          answer: function () { voice.answer(h.id, c, logic); }, hangup: function () { voice.hangup(h.id, c.id, logic); } };
      })
    } };
  }

  function zoneRow(z) {
    return Object.assign({}, z, {
      href: 'Zonas.dc.html?z=' + z.id,
      etaShort: z.is_origin ? (z.severity >= 5 ? 'origen · activo' : 'origen') : z.eta === 'Afectada' ? 'afectada'
        : z.eta_min != null ? (z.eta_min === 0 ? 'llegada ya' : '+' + z.eta_min + ' min') : 'sin amenaza',
      warnShort: z.warned ? 'Avisada' : 'Sin avisar',
      sevColor: z.severity >= 7 ? 'var(--critical)' : z.severity >= 4 ? 'var(--warning-text)' : 'var(--success)',
      accessText: z.road_cut ? 'acceso cortado' : '',
      note: (z.note || '') + (z.road_cut ? ' Acceso cortado (reportado): ' + z.road_cut + ' · +' + z.access_penalty_min + ' min para entrar desde fuera.' : '')
        + (z.power_out ? ' Sin suministro eléctrico (reportado).' : ''),
      trendLabel: { rising: '↑', falling: '↓' }[z.trend] || '→',
      hab: String(z.population).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
    });
  }

  /* A screen opened from a zone ("Acciones en la zona") shows that as a chip you can click away. */
  function zoneChip(zone, page) {
    if (!zone) return [];
    return [{ label: 'Zona: ' + zone.charAt(0).toUpperCase() + zone.slice(1) + '  ✕', cls: 'tab vl-tab vl-zonechip', sel: 'true',
      pick: function () { location.href = page + '.dc.html'; } }];
  }

  /* ── incident channel: "se acaba de hundir la carretera X" ─────────── */
  /* The form is a name and a kind; the kernel works the zone, the stock and the numbers out of the name. */
  function reportVals(logic, cid, me, supplies) {
    var st = logic.state || {}, f = st.rp || {}, data = st.rpData || { kinds: [], reports: [] };
    me = me || {}; supplies = supplies || [];
    function patch(p) { logic.setState({ rp: Object.assign({}, (logic.state || {}).rp, p) }); }
    function load() { get('/crises/' + cid + '/reports?by=' + me.id).then(function (d) { logic.setState({ rpData: d }); }).catch(function () {}); }
    var isOpen = f.open === undefined ? !!qs.get('report') : !!f.open;  // ?report=1 opens it (deep link, screenshots)
    if (isOpen && me.id && !st.rpData && !logic.__rpLoading) { logic.__rpLoading = true; load(); }
    var kind = data.kinds.filter(function (k) { return k.id === (f.kind || 'road_cut'); })[0] || { id: 'road_cut' };
    var canUnits = !!me.units, canStock = supplies.length > 0 || me.role === 'coordination';  // only what this entity can lose
    var kinds = data.kinds.filter(function (k) { return (k.id !== 'units_down' || canUnits) && (k.id !== 'resource_lost' || canStock); });
    function send() {
      if (f.sending) return;
      if (!(f.name || '').trim()) { toast('Ponle un nombre a la incidencia', 'warn'); return; }
      patch({ sending: true });
      post('/crises/' + cid + '/reports', { by: me.id, kind: kind.id, name: f.name })
        .then(function (r) {
          toast('Incidencia registrada' + (r.effects && r.effects.length ? ' · ' + r.effects[0] : ''), 'ok');
          patch({ open: false, sending: false, name: '' }); load(); reload(logic);
        }).catch(function (e) { toast(e.message, 'bad'); patch({ sending: false }); });
    }
    return { rp: {
      open: isOpen, who: me.name || '', show: function () { patch({ open: true }); load(); }, close: function () { patch({ open: false }); },
      kinds: kinds.map(function (k) { var on = k.id === kind.id; return { label: k.label, on: String(on), cls: 'vl-chipbtn' + (on ? ' is-on' : ''), pick: function () { patch({ kind: k.id }); } }; }),
      name: f.name || '', setName: function (e) { patch({ name: e.target.value }); },
      send: send, sendLabel: f.sending ? 'Enviando…' : 'Reportar',
      hasMine: data.reports.length > 0, mine: data.reports.slice(0, 3).map(function (m) {
        return { time: m.time, title: m.label + (m.zone_name ? ' · ' + m.zone_name : '') + ': ' + m.text, effects: (m.effects || []).join(' · ') || 'Registrada como aviso fiable para el agente' }; })
    } };
  }

  /* ── ActionItem / SignalItem helpers ───────────────────────────────── */
  function actionRows(logic, cid, items, by) {
    return (items || []).map(function (a) {
      var id = a.action.id;
      function decide(what) {
        return function () {
          post('/crises/' + cid + '/actions/' + id + '/' + what, { by: by || 'operador', note: '' })
            .then(function () { toast(id + (what === 'approve' ? ' aprobada' : ' rechazada'), what === 'approve' ? 'ok' : 'warn'); reload(logic); })
            .catch(function (e) { toast(e.message, 'bad'); });
        };
      }
      /* The badge shows where the action is for a person (por aprobar · esperando · en proceso · finalizada ·
       * fallida · rechazada), not the kernel's lifecycle status. */
      return Object.assign({}, a, { action: Object.assign({}, a.action, { status: a.action.state || a.action.status }),
        approve: decide('approve'), reject: decide('reject') });
    });
  }

  /* ── voice: the human picks up a call the agent is making ──────────── */
  var voice = { room: null, contact: null,
    sdk: function () {
      if (window.LivekitClient) return Promise.resolve(window.LivekitClient);
      return new Promise(function (ok, bad) {
        var s = document.createElement('script');
        s.src = 'assets/livekit-client.umd.min.js';
        s.onload = function () { ok(window.LivekitClient); };
        s.onerror = function () { bad(new Error('no se pudo cargar livekit-client')); };
        document.head.appendChild(s);
      });
    },
    join: function (token, mic) {
      return voice.sdk().then(function (lk) {
        var room = new lk.Room();
        room.on(lk.RoomEvent.TrackSubscribed, function (track) {
          if (track.kind === 'audio') { var el = track.attach(); el.autoplay = true; document.body.appendChild(el); }
        });
        room.on(lk.RoomEvent.Disconnected, function () { voice.room = null; voice.contact = null; });
        return room.connect(token.url, token.token).then(function () {
          voice.room = room;
          return mic ? room.localParticipant.setMicrophoneEnabled(true) : null;
        });
      });
    },
    answer: function (cid, contact, logic) {
      toast('Descolgando como ' + contact.entity_name + '…');
      post('/crises/' + cid + '/contacts/' + contact.id + '/answer').then(function (token) {
        voice.contact = contact.id;
        return voice.join(token, true);
      }).then(function () { toast('En llamada con el agente', 'ok'); reload(logic); })
        .catch(function (e) { toast('No se pudo atender: ' + e.message, 'bad'); });
    },
    listen: function (cid, id, takeover) {
      post('/crises/' + cid + '/contacts/' + id + '/' + (takeover ? 'takeover' : 'listen')).then(function (token) {
        voice.contact = id; return voice.join(token, !!takeover);
      }).then(function () { toast(takeover ? 'Has tomado la llamada' : 'Escuchando la llamada', 'ok'); })
        .catch(function (e) { toast(e.message, 'bad'); });
    },
    hangup: function (cid, id, logic) {
      if (voice.room) voice.room.disconnect();
      post('/crises/' + cid + '/contacts/' + id + '/hangup').then(function () { toast('Llamada terminada'); reload(logic); })
        .catch(function (e) { toast(e.message, 'bad'); });
    }
  };

  window.ValteLive = { API: API, crisisId: crisisId, view: view, asViewer: asViewer, crisis: crisis, get: get, post: post, bind: bind, unbind: unbind, reload: reload,
    header: header, zoneRow: zoneRow, reportVals: reportVals, zoneChip: zoneChip, actionRows: actionRows, roleEntity: roleEntity, voice: voice, toast: toast, fit: fit };
})();
