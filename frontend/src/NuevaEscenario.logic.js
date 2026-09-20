class Component extends DCLogic {
  /* One text box: the person writes or dictates everything, `POST /crises/draft` says what it understood, and only
     then does "Iniciar catástrofe" create it. Dictation is recorded here and transcribed by the backend (`POST /stt`),
     cut at the speaker's pauses so the text shows up sentence by sentence. */
  componentDidMount() {
    const self = this;
    ValteLive.get('/stt?warm=1').then(s => self.setState({ stt: s })).catch(() => self.setState({ stt: { available: false } }));
  }

  componentWillUnmount() { this.stopMic(); }

  append(piece) {
    piece = (piece || '').trim();
    if (!piece) return;
    const cur = (this.state && this.state.text) || '';
    this.setState({ text: cur + (cur && !/\s$/.test(cur) ? ' ' : '') + piece });
    const ta = document.getElementById('decl-text');
    if (ta) requestAnimationFrame(() => { ta.scrollTop = ta.scrollHeight; });
  }

  startMic() {
    const self = this, stt = (this.state && this.state.stt) || {};
    if (!stt.available) return this.startBrowserSpeech();
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      ValteLive.toast('El micrófono solo funciona en localhost o por https', 'warn'); return;
    }
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }).then(stream => {
      const AC = window.AudioContext || window.webkitAudioContext, ctx = new AC(), an = ctx.createAnalyser();
      an.fftSize = 1024; ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.fftSize), mic = self.mic = { stream, ctx, queue: Promise.resolve(), pending: 0, t0: Date.now(), quietFor: 0 };
      const record = () => {
        const rec = new MediaRecorder(stream), parts = [], seg = { spoke: false, t0: Date.now() };
        rec.ondataavailable = e => { if (e.data && e.data.size) parts.push(e.data); };
        rec.onstop = () => { if (seg.spoke) self.transcribe(new Blob(parts, { type: rec.mimeType })); };
        rec.start(); mic.rec = rec; mic.seg = seg;
      };
      record();
      mic.timer = setInterval(() => {
        an.getByteTimeDomainData(buf);
        let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        const rms = Math.sqrt(sum / buf.length), loud = rms > 0.02, lvl = document.getElementById('mic-lvl');
        if (lvl) lvl.style.transform = 'scale(' + (1 + Math.min(rms * 9, 0.9)).toFixed(2) + ')';
        if (loud) { mic.seg.spoke = true; mic.quietFor = 0; } else mic.quietFor += 100;
        const len = Date.now() - mic.seg.t0;
        // cut where the speaker breathes, so no word is split: a clear pause early on, any gap once the piece is long
        const gap = len > 9000 ? 250 : 700;
        if ((mic.seg.spoke && mic.quietFor >= gap && len > 2500) || len > 18000) { const old = mic.rec; record(); old.stop(); }
        const secs = Math.floor((Date.now() - mic.t0) / 1000);
        if (secs !== mic.secs) { mic.secs = secs; self.setState({ micSecs: secs }); }
      }, 100);
      self.setState({ dictating: true, micSecs: 0 });
    }).catch(e => ValteLive.toast(e && e.name === 'NotAllowedError' ? 'Permite el micrófono en el navegador para dictar' : 'No hay micrófono: ' + (e.message || e), 'warn'));
  }

  transcribe(blob) {
    const self = this, mic = this.mic || (this.mic = { queue: Promise.resolve(), pending: 0 });
    mic.pending++; self.setState({ transcribing: mic.pending });
    mic.queue = mic.queue.then(() => {   // one at a time and in order; each piece knows what is already written
      const hint = ((self.state && self.state.text) || '').slice(-200);
      return ValteLive.post('/stt?lang=es&hint=' + encodeURIComponent(hint), blob).then(r => self.append(r.text))
        .catch(e => ValteLive.toast(e.message, 'bad'));
    }).then(() => { mic.pending--; self.setState({ transcribing: mic.pending }); });
  }

  stopMic() {
    const mic = this.mic;
    if (this.speech) { try { this.speech.stop(); } catch (e) { /* already stopped */ } this.speech = null; }
    if (!mic || !mic.stream) return;
    clearInterval(mic.timer);
    if (mic.rec && mic.rec.state !== 'inactive') mic.rec.stop();
    mic.stream.getTracks().forEach(t => t.stop());
    if (mic.ctx) mic.ctx.close();
    mic.stream = null;
    this.setState({ dictating: false });
  }

  /* No transcriber on the server: Chrome, Edge and Safari can still dictate on their own. */
  startBrowserSpeech() {
    const self = this, SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { ValteLive.toast('El dictado no está instalado en el servidor y este navegador no tiene el suyo', 'warn'); return; }
    const rec = this.speech = new SR();
    rec.lang = 'es-ES'; rec.continuous = true; rec.interimResults = false;
    rec.onresult = e => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) self.append(e.results[i][0].transcript); };
    rec.onerror = e => ValteLive.toast('Dictado del navegador: ' + e.error, 'warn');
    rec.onend = () => { self.speech = null; self.setState({ dictating: false }); };
    rec.start(); this.setState({ dictating: true, micSecs: 0 });
  }

  renderVals() {
    const self = this, st = this.state || {};
    const text = st.text || '', clean = text.trim(), draft = st.draft, spec = draft && draft.spec;
    const stale = !!draft && st.draftText !== clean, fresh = !!draft && !stale;
    const fmt = n => String(n || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    const HAZ = { flood: 'Inundación', fire: 'Incendio forestal', blackout: 'Apagón', infra: 'Fallo de infraestructura', mci: 'Víctimas múltiples', other: 'Otra emergencia' };
    const TRUST = { high: 'alta', medium: 'media', low: 'baja' };
    const stt = st.stt || {}, canDictate = stt.available || !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    const clock = s => Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');

    const interpret = () => {
      if (st.reading) return;
      if (clean.length < 12) { ValteLive.toast('Cuenta algo más: qué pasa, dónde y a quién afecta', 'warn'); return; }
      self.setState({ reading: true });
      ValteLive.post('/crises/draft', { text: clean })
        .then(d => self.setState({ draft: d, draftText: clean, reading: false }))
        .catch(e => { ValteLive.toast(e.message, 'bad'); self.setState({ reading: false }); });
    };
    const create = () => {
      if (st.creating || !fresh) return;
      if (draft.blocking) { ValteLive.toast('Falta decir ' + draft.missing[0], 'warn'); return; }
      self.stopMic(); self.setState({ creating: true });
      const own = !spec.pack;   // an official plan brings its own zones, entities and stock
      ValteLive.post('/crises', {
        name: spec.name, region: spec.region, scenario: spec.hazard_type, pack: spec.pack || null,
        zones: own ? spec.zones.map(z => ({ name: z.name, population: z.population, is_origin: z.is_origin, to: z.to })) : [],
        sources: own ? spec.sources : [], resources: own ? spec.resources : [],
        reports: spec.reports || [],   // what the description says is already happening: the first data of the crisis
        transcript: clean, source: 'text',
        external_feed: true, start: true   // the data comes from the "Mundo exterior" app
      }).then(c => { location.href = 'PanelCoordinacion.dc.html?c=' + c.id; })
        .catch(e => { ValteLive.toast(e.message, 'bad'); self.setState({ creating: false }); });
    };

    const risk = Object.fromEntries(((draft && draft.risk) || []).map(r => [r.zone, r]));
    const notes = !draft ? [] : [].concat(
      draft.note ? [{ cls: 'note', glyph: 'i', text: draft.note }] : [],
      (draft.missing || []).map((m, i) => ({ cls: 'note ' + (draft.blocking && i === 0 ? 'is-block' : 'is-miss'), glyph: '!', text: 'Falta ' + m + '.' })),
      (draft.assumptions || []).map(a => ({ cls: 'note', glyph: '~', text: a })));

    return {
      text, setText: e => self.setState({ text: e.target.value }), count: clean ? clean.split(/\s+/).length + ' palabras' : '',
      onKey: e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); interpret(); } },
      boxCls: 'decl' + (st.dictating ? ' is-live' : ''),
      micCls: 'mic' + (st.dictating ? ' is-live' : '') + (canDictate ? '' : ' is-off'), micOn: String(!!st.dictating),
      micIdle: !st.dictating, micLive: !!st.dictating, micLabel: st.dictating ? 'Parar el dictado' : 'Dictar',
      micTitle: canDictate ? (st.dictating ? 'Parar' : 'Dictar en vez de escribir') : 'Dictado no disponible: instala el grupo stt en el backend o usa Chrome',
      toggleMic: () => { st.dictating ? self.stopMic() : self.startMic(); },
      micHead: st.dictating ? 'Te escucho · ' + clock(st.micSecs || 0) : st.transcribing ? 'Transcribiendo…' : 'Díctalo si vas con prisa',
      micSub: st.dictating ? (st.transcribing ? 'Transcribiendo lo anterior… sigue hablando' : 'Habla con normalidad: el texto aparece cuando haces una pausa')
        : st.transcribing ? 'Un momento, queda audio por pasar a texto'
        : !canDictate ? 'Dictado no disponible en este servidor ni en este navegador'
        : stt.available ? 'El audio se transcribe en esta máquina' + (stt.ready ? '' : ' (la primera vez tarda unos segundos en cargar)') : 'Con el dictado de tu navegador',
      examples: [
        { label: 'Incendio forestal', text: 'Incendio forestal en la Sierra Calderona. Empezó en Serra (3.300 habitantes) y el viento de poniente lo empuja hacia el sur: de Serra a Náquera en 40 minutos y de Náquera a Bétera en 1 hora. Náquera tiene 7.500 habitantes y Bétera 26.000 habitantes. El fuego está fuera de control junto al casco de Serra. Hay 30 personas atrapadas en el camping de Serra. En Náquera hay un colegio y una residencia de mayores que todavía no se han evacuado. La CV-25 ya está cortada por el humo. Tenemos 8 autobombas, 3 helicópteros, 300 mantas y 12 autobuses. Nos llegan datos de AEMET, del 112, de Copernicus y de redes sociales.' },
        { label: 'Riada · plan oficial', text: 'Riada en Paiporta. El barranco del Poyo baja desbordado. Se origina en Chiva (15.800 habitantes) y también se origina en Torrent (87.400 habitantes). Cheste tiene 8.900 habitantes, Picanya 11.700 habitantes, Paiporta 27.180 habitantes y Massanassa 9.800 habitantes. De Chiva a Cheste en 25 minutos, de Chiva a Paiporta en 38 minutos, de Torrent a Picanya en 50 minutos, de Cheste a Picanya en 19 minutos, de Paiporta a Massanassa en 17 minutos y de Picanya a Massanassa en 11 minutos. En Chiva el agua ya entra en las casas: hay vecinos atrapados en los garajes. En Torrent hay un colegio aislado junto a la avenida del Vedat. Hay 50 personas atrapadas en la residencia de mayores de Paiporta. Tenemos 12 bombas de achique, 6 embarcaciones, 800 mantas, 2400 litros de agua y 3000 raciones. Nos llegan datos de AEMET, de los aforos de la CHJ, del 112, de À Punt y de redes sociales. Aplica el plan de inundaciones.' },
        { label: 'Apagón', text: 'Apagón general en Valencia ciudad tras un fallo en la subestación de Patraix. Empezó en Patraix (57.000 habitantes) y se extiende al resto del distrito: de Patraix a Jesús en 20 minutos y de Jesús a Ruzafa en 25 minutos. Jesús tiene 52.000 habitantes y Ruzafa 24.000 habitantes. Hay una residencia de mayores en Patraix con 80 personas sin ascensor. Hay un hospital en Jesús con el grupo electrógeno al límite. En Ruzafa hay 12 personas atrapadas en el metro. Tenemos 14 generadores, 40 linternas y 600 botellas de agua. Informan Red Eléctrica, el 112 y redes sociales.' }
      ].map(x => ({ label: x.label, use: () => self.setState({ text: x.text }) })),

      noDraft: !draft, hasDraft: !!draft, stale, draftCls: 'draft' + (stale ? ' is-stale' : ''),
      asks: [['01', 'Qué pasa y dónde', 'Incendio forestal en la Sierra Calderona'], ['02', 'A quién afecta', 'Serra (3.300 habitantes), Náquera, Bétera…'],
        ['03', 'Por dónde avanza', 'De Serra a Náquera en 40 minutos'], ['04', 'Qué está pasando ya', '30 personas atrapadas en el camping'],
        ['05', 'Con qué contáis', '8 autobombas, 300 mantas'], ['06', 'Quién informa', 'AEMET, 112, redes sociales']].map(a => ({ num: a[0], name: a[1], eg: a[2] })),
      byTone: draft && draft.parsed_by === 'happyrobot' ? 'agent' : 'warning', byLabel: draft && draft.parsed_by === 'happyrobot' ? 'Leído por HappyRobot' : 'Reglas locales',
      dName: spec ? spec.name : '', dMeta: spec ? [HAZ[spec.hazard_type] || spec.hazard_type, spec.region, spec.pack ? 'plan ' + spec.pack : ''].filter(Boolean).join(' · ') : '',
      notes,
      zCount: spec ? String(spec.zones.length) : '', rCount: spec ? String(spec.resources.length) : '', sCount: spec ? String(spec.sources.length) : '',
      fCount: spec ? String((spec.reports || []).length) : '',
      dFacts: spec ? (spec.reports || []).map(f => ({ sev: f.severity + '/10', sevCls: 'fact-sev' + (f.severity >= 8 ? ' is-crit' : f.severity >= 6 ? ' is-warn' : ''),
        where: (f.place ? f.place + ', ' : '') + f.zone, text: f.text + (f.people ? ' (' + fmt(f.people) + ' personas)' : '') })) : [],
      dZones: spec ? spec.zones.map(z => ({ name: z.name, hab: z.population ? fmt(z.population) + ' hab' : '— hab', dot: 'dot' + (z.is_origin ? ' is-origin' : ''),
        dotTitle: z.is_origin ? 'Origen' : '', risk: (risk[z.name] || {}).label || '', riskCls: 'zr-risk is-' + ((risk[z.name] || {}).level || 'calm'), to: (z.to || []).map(t => '→ ' + t.name + ' ' + t.delay_min + ' min').join('   ') })) : [],
      dRes: spec ? spec.resources.map(r => ({ qty: fmt(r.qty) + (r.unit && !/^(ud|uds|unidad|unidades)\.?$/i.test(r.unit) ? ' ' + r.unit : ''), name: r.name })) : [],
      dSrc: spec ? spec.sources.map(s => ({ name: s.name, trust: TRUST[s.trust] || s.trust })) : [],

      canCreate: fresh, mustRead: !fresh, create, interpret,
      createLabel: st.creating ? 'Iniciando…' : 'Iniciar catástrofe',
      readCls: 'nav pri' + (st.reading ? ' is-wait' : ''), readLabel: st.reading ? 'Interpretando…' : stale ? 'Volver a interpretar' : 'Interpretar'
    };
  }
}
