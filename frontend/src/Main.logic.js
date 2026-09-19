class Component extends DCLogic {
  componentDidMount() {
    // All of them, not only the active ones: a new crisis stacks on top, it never replaces another.
    ValteLive.bind(this, function () { return ValteLive.get('/crises'); }, { noCrisis: true });
  }
  componentWillUnmount() { ValteLive.unbind(this); }
  renderVals() {
    var st = this.state || {}, list = st.data || [];
    var HAZ = { flood: 'Inundación', fire: 'Incendio forestal', blackout: 'Apagón', infra: 'Fallo de infraestructura', mci: 'Víctimas múltiples', other: 'Otro' };
    var active = list.filter(function (c) { return c.status === 'active'; });
    var closed = list.filter(function (c) { return c.status !== 'active'; }).slice(0, 4);
    var big = active.length <= 4 ? 64 : active.length <= 6 ? 44 : 34;   // the more there are, the tighter the stack
    function row(c, i, on) {
      return { num: ('0' + (i + 1)).slice(-2), name: c.name, href: 'PanelCoordinacion.dc.html?c=' + c.id,
        size: on ? big : 28, pad: on ? Math.round(big * 0.44) : 12, color: on ? 'var(--ink)' : 'var(--ink-muted)',
        meta: (HAZ[c.hazard] || c.hazard) + ' · ' + c.code + (on ? ' · severidad ' + c.severity + '/10' : ' · cerrada') };
    }
    return {
      has: !st.loaded || list.length > 0, none: !!st.loaded && list.length === 0,
      crises: active.map(function (c, i) { return row(c, i, true); })
        .concat(closed.map(function (c, i) { return row(c, active.length + i, false); }))
    };
  }
}
