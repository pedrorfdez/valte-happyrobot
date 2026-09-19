/* Valte · the zones on the territory.
 *
 * Leaflet, deliberately non-interactive: the dashboard is a fixed canvas scaled with a CSS transform, and Leaflet's
 * drag/zoom maths does not survive a scaled ancestor. Clicks on a zone are plain DOM events, so they do. */
(function () {
  var map = null, layers = null, host = null, drawn = '';
  var INFO = '#1E3F8F';

  function sevColor(s) { return s >= 7 ? '#B8360F' : s >= 4 ? '#C28A00' : '#2B6638'; }
  function hash(str) { var h = 0; for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0; return Math.abs(h); }
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function ensure(container) {
    if (map && host === container && document.body.contains(container)) return map;
    if (map) { map.remove(); map = null; }
    host = container; drawn = '';
    map = L.map(container, { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
      boxZoom: false, keyboard: false, touchZoom: false, zoomSnap: 0.1, attributionControl: true });
    map.attributionControl.setPrefix('');
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map);
    layers = L.layerGroup().addTo(map);
    return map;
  }

  /* zones: rows from /zones (+ sel flag); signals: SignalItem rows with a precise location; onPick(zoneId). */
  function sync(container, zones, signals, onPick) {
    var located = zones.filter(function (z) { return z.centroid; });
    if (!container || !window.L || located.length === 0) return false;
    var m = ensure(container);
    var key = JSON.stringify([zones.map(function (z) { return [z.id, z.severity, z.trend, z.eta_min, z.warned, z.road_cut, !!z.centroid, z.cls]; }),
      signals.map(function (s) { return s.signal.id; })]);
    if (key === drawn) return true;
    var first = drawn === '';
    drawn = key;
    if (first) {
      m.invalidateSize();
      m.fitBounds(L.latLngBounds(located.map(function (z) { return [z.centroid.lat, z.centroid.lng]; })), { paddingTopLeft: [70, 60], paddingBottomRight: [300, 60], maxZoom: 13 });
    }
    layers.clearLayers();
    var byId = {}; zones.forEach(function (z) { byId[z.id] = z; });

    zones.forEach(function (z) {            // how the hazard travels: origin → downstream, with the delay
      (z.to || []).forEach(function (e) {
        var t = byId[e.zone];
        if (!z.centroid || !t || !t.centroid) return;
        var a = [z.centroid.lat, z.centroid.lng], b = [t.centroid.lat, t.centroid.lng];
        L.polyline([a, b], { color: INFO, weight: 2, opacity: .8, dashArray: '6 6', interactive: false }).addTo(layers);
        var pa = m.latLngToLayerPoint(a), pb = m.latLngToLayerPoint(b), deg = Math.atan2(pb.y - pa.y, pb.x - pa.x) * 180 / Math.PI;
        var at = [a[0] + (b[0] - a[0]) * .62, a[1] + (b[1] - a[1]) * .62];
        L.marker(at, { interactive: false, icon: L.divIcon({ className: 'vl-map-arrow', iconSize: [90, 18], iconAnchor: [45, 9],
          html: '<span style="display:inline-block;transform:rotate(' + deg.toFixed(1) + 'deg)">▶</span> +' + e.delay_min + ' min' }) }).addTo(layers);
      });
    });

    signals.forEach(function (s) {          // street-level reports, scattered around their zone so they do not pile up
      var z = byId[(s.signal.location || {}).zone];
      if (!z || !z.centroid) return;
      var h = hash(s.signal.id), ang = (h % 360) * Math.PI / 180, r = 0.004 + (h % 7) * 0.0014;
      var sev = Math.max.apply(null, [0].concat((s.signal.claims || []).map(function (c) { return c.severity_hint || 0; })));
      L.circleMarker([z.centroid.lat + Math.sin(ang) * r, z.centroid.lng + Math.cos(ang) * r * 1.3],
        { radius: 5, color: '#fff', weight: 1.5, fillColor: sevColor(sev), fillOpacity: .95 })
        .bindTooltip('<b>' + esc(s.time) + ' · ' + esc(s.sourceName) + '</b><br>' + esc((s.signal.content || '').slice(0, 140)), { className: 'vl-map-tip', direction: 'top' })
        .addTo(layers);
    });

    // Towns in the same valley sit a few pixels apart: give each label the first spot where it collides with nothing.
    var boxes = [], LH = 46;
    var radiusOf = function (z) { return Math.max(11, Math.min(30, Math.sqrt(z.population || 1000) / 9)); };
    var metaOf = function (z) {
      var eta = z.is_origin ? 'origen' : z.eta === 'Afectada' ? 'afectada' : z.eta_min != null ? (z.eta_min === 0 ? 'llega ya' : '+' + z.eta_min + ' min') : '';
      return z.severity + '/10 ' + (z.trendLabel || '') + (eta ? ' · ' + eta : '') +
        (z.warned ? '' : ' · <b>sin avisar</b>') + (z.road_cut ? ' · <b>acceso cortado</b>' : '');
    };
    var widthOf = function (z) { return Math.max(z.name.length * 10.5, metaOf(z).replace(/<[^>]+>/g, '').length * 6.7) + 22; };
    var hits = function (r) { return boxes.some(function (b) { return r.x < b.x + b.w && r.x + r.w > b.x && r.y < b.y + b.h && r.y + r.h > b.y; }); };
    located.forEach(function (z) { var p = m.latLngToLayerPoint([z.centroid.lat, z.centroid.lng]), r = radiusOf(z); boxes.push({ x: p.x - r, y: p.y - r, w: 2 * r, h: 2 * r }); });
    var spot = {};
    located.slice().sort(function (a, b) { return b.centroid.lat - a.centroid.lat; }).forEach(function (z) {
      var p = m.latLngToLayerPoint([z.centroid.lat, z.centroid.lng]), r = radiusOf(z) + 4, w = widthOf(z), dy = LH * 0.95;
      var options = [['right', r, 0], ['left', -r, 0], ['bottom', 0, r], ['top', 0, -r], ['right', r, dy], ['right', r, -dy],
        ['left', -r, dy], ['left', -r, -dy], ['right', r, 2 * dy], ['left', -r, 2 * dy]].map(function (o) {
        var x = o[0] === 'right' ? p.x + o[1] : o[0] === 'left' ? p.x + o[1] - w : p.x - w / 2;
        var y = o[0] === 'bottom' ? p.y + o[2] : o[0] === 'top' ? p.y + o[2] - LH : p.y + o[2] - LH / 2;
        return { dir: o[0], offset: [o[1], o[2]], rect: { x: x, y: y, w: w, h: LH } };
      });
      var pick = options.filter(function (o) { return !hits(o.rect); })[0] || options[0];
      spot[z.id] = pick;
      boxes.push(pick.rect);
    });

    located.forEach(function (z) {
      var radius = radiusOf(z);
      var mk = L.circleMarker([z.centroid.lat, z.centroid.lng], { radius: radius, color: z.is_origin ? '#B8360F' : '#0E0D0C',
        weight: z.is_origin ? 3 : 1.5, fillColor: sevColor(z.severity), fillOpacity: z.severity ? .78 : .25, className: 'vl-map-zone' }).addTo(layers);
      mk.bindTooltip('<span class="vl-map-name">' + esc(z.name) + '</span><span class="vl-map-meta">' + metaOf(z) + '</span>',
        { permanent: true, direction: spot[z.id].dir, offset: spot[z.id].offset, className: 'vl-map-label' + (/is-on/.test(z.cls || '') ? ' is-on' : '') });
      mk.on('click', function () { onPick(z.id); });
    });
    return true;
  }

  function destroy() { if (map) { map.remove(); map = null; host = null; drawn = ''; } }

  window.ValteMap = { sync: sync, destroy: destroy };
})();
