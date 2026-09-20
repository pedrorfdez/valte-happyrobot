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
    var raw = typeof Blob !== 'undefined' && body instanceof Blob;  // a recording goes as it is (dictation)
    var headers = body && !raw ? { 'content-type': 'application/json' } : {};
    if (KEY) headers['X-Valte-Key'] = KEY;
    return fetch(API + path, {
      method: method,
      headers: headers,
      body: raw ? body : body ? JSON.stringify(body) : undefined
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
      load(cid).then(function (data) {
        if (denied(data && data.header)) { location.replace(homeOf(data.header.access.role)); return; }
        if (PAGE === 'Zonas' && oneZone(data && data.header)) { location.replace(homeOf(view().role)); return; }
        logic.setState({ data: data, error: null, loaded: true });
      })
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
        'incident.opened', 'incident.updated', 'incident.dismissed', 'incident.merged',
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
  var TITLES = { Zonas: 'Zonas', Acciones: 'Acciones', Incidencias: 'Incidencias', Recursos: 'Recursos', Contactos: 'Contactos' };
  var PANELS = { coordination: 'PanelCoordinacion.dc.html', authority: 'PanelAutoridad.dc.html', responder: 'PanelRespuesta.dc.html' };
  var KIND = { coordination: 'Coordinación', authority: 'Autoridad', responder: 'Respuesta', civilian: 'Población' };

  /* What each entity gets of the dashboard comes from the kernel (header.access): every screen for coordination,
     authorities and responders; for the population only the directory and the incident channel. */
  var SCREEN = { Zonas: 'zones', Acciones: 'actions', Incidencias: 'signals', Recursos: 'resources', Contactos: 'contacts' };
  function homeOf(role) { return PANELS[role] || 'Contactos.dc.html'; }
  function allowed(h, page) { return !SCREEN[page] || !h || !h.access || h.access.screens.indexOf(SCREEN[page]) >= 0; }
  function denied(h) { return !allowed(h, PAGE); }
  /* A map of one zone says nothing the panel does not: with a single zone in sight there is no Zonas screen. */
  function oneZone(h) { return !!(h && h.kpis && h.kpis.zones && h.kpis.zones.total <= 1); }
  function entityHref(r) {
    return PANELS[r.role] ? PANELS[r.role] + '?e=' + encodeURIComponent(r.entity_id)
      : 'Contactos.dc.html?as=' + encodeURIComponent(r.entity_id) + '&asrole=' + r.role;
  }

  function roleEntity(h, role) {
    var saved = localStorage.getItem('valte.' + role);
    var options = (h.roles || []).filter(function (r) { return r.role === role; });
    var prefer = { authority: 'alcaldia-paiporta', responder: 'bomberos-vlc' }[role];
    return options.filter(function (r) { return r.entity_id === saved; })[0] ||
      options.filter(function (r) { return r.entity_id === prefer; })[0] || options[0] || null;
  }

  /* The entity dropdown is a <details>: a click anywhere else, or Esc, closes it. */
  function closeEnts(except) {
    [].forEach.call(document.querySelectorAll('details.vl-ent[open]'), function (el) { if (el !== except) el.removeAttribute('open'); });
  }
  document.addEventListener('click', function (ev) { closeEnts(ev.target.closest ? ev.target.closest('details.vl-ent') : null); });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeEnts(null); });

  function header(logic, page, kpisOverride) {
    var st = logic.state || {}, d = st.data || {}, h = d.header;
    if (!h) return { hd: { title: 'Valte', sub: st.error || 'cargando…', sev: 0, trend: 'stable', ents: [], kpis: [], ringing: [], backHref: 'Main.dc.html' } };
    var clock = st.clock || h.clock, k = kpisOverride || h.kpis, isPanel = page.indexOf('Panel') === 0;
    var pace = clock.paused ? 'en pausa' : clock.slowmo ? '1× · llamada en curso' : clock.speed + '×';
    var line = h.code + ' · ' + clock.clock + ' · ' + clock.elapsed + ' · ' + pace + (h.status !== 'active' ? ' · CERRADA' : '');
    var pageRole = { PanelCoordinacion: 'coordination', PanelAutoridad: 'authority', PanelRespuesta: 'responder' }[page];
    var acc = h.access || { role: view().role, screens: Object.keys(SCREEN).map(function (p) { return SCREEN[p]; }) };
    var homeScreen = !isPanel && !PANELS[acc.role] && homeOf(acc.role).indexOf(page + '.') === 0;  // the population has no panel: its home is this screen
    if (homeScreen) { isPanel = true; pageRole = acc.role; }
    /* One dropdown, on every screen: it shows the entity you are looking as, and opens onto every entity of the crisis,
       by role. The entity keeps mattering outside its panel: Zonas, Acciones, Incidencias… show what concerns IT.
       Picking another entity always lands on THAT entity's main dashboard (its panel; the population's is Contactos):
       the screen you are on may not even exist for it (a town hall with one zone has no map). */
    var curRole = isPanel ? pageRole : view().role;
    var cur = roleEntity(h, curRole);
    var ents = [{ kind: KIND[curRole], name: cur ? cur.label : '—',
      groups: ['coordination', 'authority', 'responder', 'civilian'].map(function (role) {
        return { kind: KIND[role], items: (h.roles || []).filter(function (r) { return r.role === role; }).map(function (r) {
          var on = r === cur;
          return { href: entityHref(r), name: r.label,
            cls: 'vl-ent__opt' + (on ? ' is-on' : ''), cur: on ? 'true' : 'false' };
        }) };
      }).filter(function (g) { return g.items.length; }) }];
    var backHref = isPanel ? 'Main.dc.html' : homeOf(view().role);
    function kpi(href, label, num, rest, color, first, off) {
      var on = !homeScreen && href.indexOf(page + '.') === 0;  // pressing the open submenu again leaves it, back to the panel
      return { page: href.split('.')[0], href: off ? '#' : on ? backHref : href, label: label, num: num, rest: rest, color: color,
        cls: 'kpi-link' + (on ? ' is-on' : '') + (off ? ' is-off' : ''), off: off ? 'true' : 'false', tab: off ? '-1' : '0',
        style: 'flex-grow: 1; display: flex; flex-direction: column; gap: 4px;' + (first ? '' : ' border-left: 1px solid var(--line-strong); padding-left: 24px;') };
    }
    var me = localStorage.getItem('valte.actingAs') || '';
    return { hd: {
      title: PANELS[pageRole] ? h.name : TITLES[page] || h.name, sub: PANELS[pageRole] ? line : h.name + ' · ' + line,
      backHref: backHref,
      sev: h.severity, trend: h.trend, level: h.emergency_level > 0, levelLabel: 'Nivel ' + h.emergency_level, ents: ents,
      kpis: [
        kpi('Zonas.dc.html', 'Zonas', k.zones.warned, '/ ' + k.zones.total + ' avisadas', 'var(--ink)', true, k.zones.total <= 1),
        kpi('Acciones.dc.html', 'Acciones', k.actions.pending_approval, 'por aprobar · ' + k.actions.total + ' en total', k.actions.pending_approval ? 'var(--warning-text)' : 'var(--ink)'),
        kpi('Incidencias.dc.html', 'Incidencias', k.incidents.open, '· ' + k.incidents.unattended + ' sin atender · ' + k.incidents.candidate + ' sin confirmar',
          k.incidents.unattended ? 'var(--critical)' : 'var(--ink)'),
        kpi('Recursos.dc.html', 'Recursos', k.units.available, '/ ' + k.units.total + ' ' + (k.units.label || 'unidades libres'), k.units.total && k.units.available / k.units.total <= 0.2 ? 'var(--critical)' : 'var(--ink)'),
        kpi('Contactos.dc.html', 'Contactos', k.contacts.entities != null ? k.contacts.entities : k.contacts.total,
          '· ' + (k.contacts.unreachable != null ? k.contacts.unreachable : k.contacts.unanswered) + ' sin respuesta',
          (k.contacts.unreachable || k.contacts.unanswered) ? 'var(--critical)' : 'var(--ink)')
      ].filter(function (t) { return allowed(h, t.page); }).map(function (t, i) { return i ? t : Object.assign(t, { style: t.style.split(' border-left')[0] }); }),
      ringing: (h.ringing || []).filter(function (c) { return c.channel === 'voice'; }).map(function (c) {
        var live = c.status === 'in_progress';
        return { title: (live ? 'Llamada en curso · ' : 'Llamada entrante · ') + c.entity_name, ask: (c.brief || {}).ask || '',
          meta: (c.action_id || '') + ' · ' + c.time, entity: c.entity_name, canAnswer: !live, live: live && voice.contact === c.id,
          answer: function () { voice.answer(h.id, c, logic); }, hangup: function () { voice.hangup(h.id, c.id, logic); } };
      })
    } };
  }

  function zoneRow(z, i, all) {
    var alone = !!all && all.length <= 1;
    return Object.assign({}, z, {
      href: alone ? '#' : 'Zonas.dc.html?z=' + z.id, linkCls: alone ? 'is-still' : '',
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
  /* The form is a name and a kind; the kernel works the zone, the stock and the numbers out of the name.
     From the population it is a lead, not a fact: low reliability, and nothing changes until someone else corroborates it. */
  var CONF = { low: 'baja', medium: 'media', high: 'alta' };
  /* One example per kind, so the free-text box is discoverable instead of a blank stare. Falls back to the
     original placeholder for any kind this list has not caught up with yet. */
  var RP_EX = {
    road_cut: 'Se hunde el puente de la CV-36 en Paiporta',
    people_trapped: 'Hay 6 personas atrapadas en un bajo de la calle Sant Josep',
    building_damage: 'Se ha derrumbado parte del tejado de la residencia de Paiporta',
    power_out: 'Se ha ido la luz en todo Paiporta',
    resource_lost: 'Solo quedan 3 bombas de achique',
    units_down: 'Se nos ha averiado una unidad de rescate',
    shelter_full: 'El polideportivo de Paiporta ya no admite a nadie más',
    other: 'Se hunde el puente de la CV-36 en Paiporta',
    zone_new: 'Se ha roto la mota y ahora se inunda Sedaví, 10.500 habitantes, llega en 25 min',
    resource_new: 'Nos llegan 200 mantas y 4 bombas de achique',
    entity_new: 'Se suma Cruz Roja Valencia con 12 voluntarios para rescate y 2 embarcaciones',
    action_done: 'Ya hemos cortado el puente de la CV-36 por nuestra cuenta'
  };
  var RP_GROUP_LABEL = { world: 'Qué ha cambiado' };
  function reportVals(logic, cid, me, supplies) {
    var st = logic.state || {}, f = st.rp || {}, data = st.rpData || { kinds: [], reports: [] };
    me = me || {}; supplies = supplies || [];
    function patch(p) { logic.setState({ rp: Object.assign({}, (logic.state || {}).rp, p) }); }
    function load() { get('/crises/' + cid + '/reports?by=' + me.id).then(function (d) { logic.setState({ rpData: d }); }).catch(function () {}); }
    var isOpen = f.open === undefined ? !!qs.get('report') : !!f.open;  // ?report=1 opens it (deep link, screenshots)
    if ((isOpen || me.role === 'civilian') && me.id && !st.rpData && !logic.__rpLoading) { logic.__rpLoading = true; load(); }  // the population sees its own reports without opening the form
    var kind = data.kinds.filter(function (k) { return k.id === (f.kind || 'other'); })[0] || { id: 'other' };
    var worldKinds = data.kinds.filter(function (k) { return k.group === 'world'; });
    function chip(k) {
      var on = k.id === kind.id;
      return { label: k.label, on: String(on), cls: 'vl-chipbtn' + (on ? ' is-on' : ''),
        pick: function () { patch({ kind: on ? 'other' : k.id }); } };
    }
    function send() {
      if (f.sending) return;
      if (!(f.name || '').trim()) { toast('Ponle un nombre a la incidencia', 'warn'); return; }
      patch({ sending: true });
      post('/crises/' + cid + '/reports', { by: me.id, kind: kind.id, name: f.name })
        .then(function (r) {
          toast('Incidencia registrada' + (r.effects && r.effects.length ? ' · ' + r.effects[0] : ''), 'ok');
          patch({ open: false, sending: false, name: '', kind: 'other' }); load(); reload(logic);
        }).catch(function (e) { toast(e.message, 'bad'); patch({ sending: false }); });  // keeps f.name so the person can fix it
    }
    var low = data.reliability === 'low';
    return { rp: {
      low: low, open: isOpen, who: (me.name || '') + (low ? ' · fiabilidad baja' : ''), show: function () { patch({ open: true }); load(); }, close: function () { patch({ open: false }); },
      hasWorld: worldKinds.length > 0, worldGroupLabel: RP_GROUP_LABEL.world,
      worldKinds: worldKinds.map(chip),
      hint: kind.hint || '',
      name: f.name || '', namePh: RP_EX[kind.id] || RP_EX.other, setName: function (e) { patch({ name: e.target.value }); },
      send: send, sendLabel: f.sending ? 'Enviando…' : 'Reportar',
      hasMine: data.reports.length > 0, mine: data.reports.slice(0, 3).map(function (m, i) {
        var effects = m.reliability === 'low'
          ? ['Fiabilidad ' + (CONF[m.confidence] || 'baja') + (m.confidence === 'low' || !m.confidence ? ' · sin corroborar todavía: no ha cambiado nada' : ' · corroborado por otras fuentes')]
          : (m.effects && m.effects.length ? m.effects : ['Registrada como aviso fiable para el agente']);
        var hasLines = i === 0 && effects.length > 1;
        return { time: m.time, title: m.label + (m.zone_name ? ' · ' + m.zone_name : '') + ': ' + m.text,
          hasLines: hasLines, singleLine: !hasLines, lines: effects.map(function (e) { return { text: e }; }),
          effects: hasLines ? '' : effects.join(' · ') };
      })
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

  function incidentRows(items) {
    return (items || []).map(function (i) {
      return { href: 'Incidencias.dc.html?open=' + i.id, prioCls: 'vl-prio ' + (i.priority || 'p3').toLowerCase(), title: i.title,
        tone: i.tone, stateLabel: i.state_label, evidenceLabel: i.evidenceLabel,
        attention: i.waitingLabel || i.attendedBy || '—', attColor: i.waitingLabel ? 'var(--critical)' : 'var(--ink-muted)' };
    });
  }

  /* ── voice: the human picks up a call the agent is making ──────────── */
  /* Why the microphone would not open. Getting this wrong looks like a broken call, so it is said in plain words. */
  function micProblem(e) {
    var n = (e && e.name) || '';
    if (typeof isSecureContext !== 'undefined' && !isSecureContext)
      return 'sin micrófono: el navegador solo lo permite en localhost o por https, y has abierto el panel por otra dirección';
    if (n === 'NotAllowedError' || n === 'SecurityError') return 'sin micrófono: permíteselo al navegador (el candado de la barra de direcciones) y vuelve a descolgar';
    if (n === 'NotFoundError' || n === 'OverconstrainedError') return 'sin micrófono: este equipo no tiene ninguno';
    if (n === 'NotReadableError') return 'sin micrófono: lo está usando otro programa';
    return 'sin micrófono: ' + ((e && e.message) || n || 'no se pudo abrir');
  }

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
          if (track.kind !== 'audio') return;
          var el = track.attach();
          el.autoplay = true;
          document.body.appendChild(el);
          var played = el.play();
          if (played && played.catch) played.catch(function () {  // connected but silent: it looks exactly like a call that failed
            toast('Pulsa en cualquier sitio de la página para oír al agente', 'warn');
            var go = function () { el.play(); document.removeEventListener('click', go); };
            document.addEventListener('click', go);
          });
        });
        room.on(lk.RoomEvent.Disconnected, function () { voice.room = null; voice.contact = null; });
        return room.connect(token.url, token.token).then(function () {
          voice.room = room;
          if (!mic) return { muted: '' };
          // Connected is connected: a microphone that will not open leaves you listening, it does not drop the call.
          return room.localParticipant.setMicrophoneEnabled(true).then(
            function () { return { muted: '' }; }, function (e) { return { muted: micProblem(e) }; });
        });
      });
    },
    answer: function (cid, contact, logic) {
      toast('Descolgando como ' + contact.entity_name + '…');
      post('/crises/' + cid + '/contacts/' + contact.id + '/answer').then(function (token) {
        voice.contact = contact.id;
        return voice.join(token, true);
      }).then(function (r) {
        toast(r && r.muted ? 'En llamada con el agente, ' + r.muted : 'En llamada con el agente', r && r.muted ? 'warn' : 'ok');
        reload(logic);
      }).catch(function (e) {
        voice.contact = null;  // it never got in: do not leave the card thinking it is live
        toast('No se pudo atender: ' + ((e && e.message) || e), 'bad');
        reload(logic);
      });
    },
    listen: function (cid, id, takeover) {
      post('/crises/' + cid + '/contacts/' + id + '/' + (takeover ? 'takeover' : 'listen')).then(function (token) {
        voice.contact = id; return voice.join(token, !!takeover);
      }).then(function (r) {
        var base = takeover ? 'Has tomado la llamada' : 'Escuchando la llamada';
        toast(r && r.muted ? base + ', ' + r.muted : base, r && r.muted ? 'warn' : 'ok');
      }).catch(function (e) { voice.contact = null; toast((e && e.message) || e, 'bad'); });
    },
    hangup: function (cid, id, logic) {
      if (voice.room) voice.room.disconnect();
      post('/crises/' + cid + '/contacts/' + id + '/hangup').then(function () { toast('Llamada terminada'); reload(logic); })
        .catch(function (e) { toast(e.message, 'bad'); });
    }
  };

  window.ValteLive = { API: API, crisisId: crisisId, view: view, asViewer: asViewer, crisis: crisis, get: get, post: post, bind: bind, unbind: unbind, reload: reload,
    header: header, zoneRow: zoneRow, reportVals: reportVals, zoneChip: zoneChip, actionRows: actionRows, incidentRows: incidentRows,
    roleEntity: roleEntity, voice: voice, toast: toast, fit: fit };
})();
