# Valte Pantallas → App-v2 Mapping

Reference unpacked from `origin/feat/valte-v2` into `docs/reference/valte-pantallas/` via `scripts/unpack-valte-pantallas.mjs`.
Design source: `Valte · Pantallas.html` bundle + `frontend/design/*.body.html` + `frontend/assets/*`.

## Design files → App-v2 screens → Projection functions

| Design file | App-v2 screen | Projection function | Notes |
|---|---|---|---|
| `Main.body.html` | `screens/list.js` | `fetchRuns` | run_id, pack_id, zone_count; list row uses `font-display` 64px as in Main |
| `PanelCoordinacion.body.html` | `main.js` coordination | `buildViewerProjection` with `role=coordination` | global: all zones/incidents/actions/resources/contacts |
| `PanelAutoridad.body.html` | `main.js` authority | `filterZones` / `filterIncidents` | jurisdiction: `viewerEntity.jurisdiction_zone_ids` filters zones + incidents |
| `PanelRespuesta.body.html` | `main.js` responder | `filterZones` / `filterIncidents` / `filterActions` | responder jurisdiction same as authority path |
| `Zonas.body.html` | `screens/zones.js` | `filterZones` + `display.x/y` | map dots positioned `left:${x}% top:${y}%`, `data-x`/`data-y` attrs |
| `Acciones.body.html` | `screens/actions.js` | `filterActions` + `approver_entity_ids` | pending_approval only for eligible viewer in approver allowlist + actor/target |
| `Recursos.body.html` | `screens/resources.js` | `filterResources` by `owner_entity_id` | coordination sees all, authority/responder sees owned only |
| `Contactos.body.html` | `screens/contacts.js` | `buildContacts` join | no send/call/email controls; `simulated_transcript` sanitized; `Sin comunicaciones registradas` when empty |
| `Senales.body.html` | (excluded) | `redactSignals` | never render; `signals`/`lessons`/`plan_lessons` stripped, evidence redacted |

## Source locations

- Reference: `docs/reference/valte-pantallas/design/*.body.html` + `docs/reference/valte-pantallas/assets/valte-tokens.css` + `Valte · Pantallas.html` bundle
- Adapter: `app-v2/src/adapter/projection.js` (`filterZones`, `filterIncidents`, `filterActions`, `filterResources`, `buildContacts`, `computeKPIs`, `redactSignals`, `buildViewerProjection`)
- Screens: `app-v2/src/screens/*.js` render projection output into 1440×900 fixed canvas
- Data: Supabase Gateway `GET /api/runs`, `GET /api/snapshot` — sole data source

## Exclusion

`Senales` is present in `docs/reference/valte-pantallas/design/Senales.body.html` for reference only. App-v2 must never import or render it; `redactSignals` ensures it never enters the view model.
