# Valte v2 · backend

Kernel del sistema agéntico de crisis (reto HappyRobot, HackSpain 2026). FastAPI + SQLite.
Mantiene el estado del mundo, mueve un escenario dinámico, valida y ejecuta lo que deciden los
workflows de HappyRobot (HR), contacta de verdad con las personas y deja que un humano intervenga.

```
simulador ──raw──▶ PedroD-ingest-* ──/perceptions──▶ ┐            PedroD-crisis-intake ─/api/commands─▶ ┐
                                                     ▼                                                  ▼
        núcleo: señales+confianza · zonas y propagación · tripwires · acciones (validar, aprobar, escalar)
                                   · recursos · plan e incidentes · contactos · eventos
            │ despertar táctico                     │ el plan ya no describe el mundo
            ▼                                       ▼
   PedroD-coordinator ─/decisions─▶        PedroD-crisis-command ─replace_plan─▶
            │ acciones aprobadas
            ▼
   PedroD-outreach (email real) · PedroD-outreach-call (llamada web real)
            │ transcripción
            ▼
   PedroD-crisis-response-coordination ─record_outcome─▶ efectos · sin respuesta ⇒ escalado ⇒ re-despertar
```

Los cerebros **solo proponen**; el núcleo valida (capacidades, jurisdicción, unidades libres, duplicados),
pide aprobación humana para lo grave y ejecuta. `crisis-command` es estratégico (incidentes P0–P3 y
objetivos, no emite acciones); `coordinator` es táctico y es la única fuente de acciones.

## Arrancar

```bash
cd backend
uv sync
scripts/dev_server.sh 8010          # un solo worker, sin --reload (el motor vive en el proceso)
scripts/tunnel.sh 8010              # en OTRA línea de comandos; escribe la URL pública en .public_url
uv run python scripts/provision_workflows.py   # crea/actualiza los PedroD-* (idempotente)
curl localhost:8010/meta            # qué está cableado
```

- El puerto **8000 lo ocupa un uvicorn antiguo del v1**; por eso se usa 8010 (`VITE_API_BASE_URL` debe apuntar ahí).
- El túnel (`ssh` → localhost.run, sin instalar nada) cambia de URL cada vez. No hay que tocar HR: cada
  disparo lleva `callback_base` y los nodos llaman a `{{callback_base}}/...`.
- Si el túnel cae, **el sistema sigue**: el estado viaja en el payload del disparo y el motor lee la salida del
  run en HR (`/runs/{id}/outputs/...`) cuando el callback no llega. Si HR tampoco responde, entra la percepción
  guionizada del pack o el cerebro local, siempre etiquetados (`perceived_by: fallback`, `origin: local-brain`).

`.env` (en la raíz de `valte-v2/`): `HAPPYROBOT_API_KEY`, `HAPPYROBOT_WEBHOOK_SECRET` (bearer que HR nos envía;
ya generado), `DEMO_EMAIL_TO` (**obligatorio para los emails reales**: todo email se reescribe a ese buzón;
vacío = no se envía nada), `VALTE_SIM_SPEED` (20), `VALTE_BRAIN` (`auto|hr|local`), `VALTE_OUTREACH_MODE`
(`real|dry`), `VALTE_DB_URL` (por defecto `backend/valte.db`; **no** se usa `DATABASE_URL`, que es Supabase).

## Quién puede llamar a qué

El túnel expone el servidor entero, no solo los callbacks. `valte/api/gate.py` lo acota: **solo esta máquina** usa la API
libremente. Una petición que llega de fuera (trae `X-Forwarded-*` o su `Host` no es loopback: túnel o red local) solo puede usar
los contratos de HappyRobot (que además piden su bearer), los enlaces de aprobación de los emails (`/a/{token}`), `/health` y los
estáticos del front. Todo lo demás responde 403, salvo que exista `VALTE_DASHBOARD_TOKEN` y la petición lo presente
(`?key=` o cabecera `X-Valte-Key`). Para abrir el dashboard en otro dispositivo (el móvil de un juez): pon el token en `.env`,
reinicia y abre `https://<túnel>/app/?key=<token>`; el front lo recuerda.

## Workflows en HappyRobot (todos nuevos, prefijo `PedroD-`)

| Workflow | Forma | Vuelve a |
|---|---|---|
| `PedroD-ingest-calls` / `-social` / `-news` | webhook → Extract → POST | `POST /perceptions` |
| `PedroD-coordinator` | webhook → Extract → POST | `POST /decisions` |
| `PedroD-proactive` | webhook → Extract → POST | `POST /hr/proactive` |
| `PedroD-crisis-parse` | webhook → Extract | ninguno: `POST /crises/draft` espera y lee la salida del run |
| `PedroD-crisis-review` | webhook → Extract | ninguno: tras `POST /crises/{id}/close` el kernel lee la salida y guarda las lecciones con evidencia real |
| `PedroD-crisis-intake` | webhook → Extract → POST | `POST /api/commands` `upsert_signal` |
| `PedroD-crisis-command` | webhook → Extract → POST | `POST /api/commands` `replace_plan` |
| `PedroD-crisis-response-coordination` | webhook → Extract → POST | `POST /api/commands` `record_outcome` |
| `PedroD-outreach` | webhook → Extract → Send email → POST | `POST /hr/outreach/result` |
| `PedroD-outreach-call`, `PedroD-emergency-call`, `PedroD-crisis-start` | Web call → agente de voz es-ES | transcripción por API |

Están definidos como código en `valte/hr/specs.py` (prompts incluidos, neutros de escenario: zonas, doctrina
y verbos viajan en el estado). `valte/hr/client.py` **rechaza cualquier escritura sobre un workflow que no
sea `PedroD-*`** (lo verifica contra HR, no contra nuestra base): los workflows de otros equipos no se tocan.

**`PedroD-proactive` — la ronda que nadie pide.** El coordinador reacciona a eventos; lo que no produce evento no es trabajo
de nadie. Cada `VALTE_PROACTIVE_EVERY_S` segundos (45 por defecto; 0 lo apaga) el kernel barre cada crisis en marcha
(`valte/engine/patrol.py`): zonas en el camino del peligro sin avisar, evacuaciones sin plazas de albergue, avisos que llevan
demasiado esperando, dotaciones aparcadas en una zona que se calmó, stock a punto de agotarse, zonas que empeoran sin nadie libre,
aprobaciones sin firmante. Los hallazgos (`pat-…`, cada uno con una acción sugerida ya validable) viajan con el estado completo al
workflow, que responde con acciones por el mismo pipeline que todo lo demás (`origin=proactive`: validación, aprobaciones,
contactos reales) y puede **mover recursos** con tres verbos de sistema nuevos (`valte/core/logistics.py`): `recall_units`
(retira una dotación antes de tiempo), `transfer_resource` (el stock cambia de entidad; quien presta conserva un 25 %) y
`request_resupply` (reposición desde fuera, llega con retraso: `state.incoming_resupply`). Solo gasta un run cuando el barrido
encuentra algo **nuevo** (más una ronda «en calma» cada 4; tope de 60 runs por crisis); sin HappyRobot aplica las sugerencias
del barrido tal cual. Una ronda que cambia algo despierta al coordinador y sale en «Últimos cambios».

Cosas aprendidas de la API (útiles si se toca `specs.py`):
- El nodo POST envía `params` como **query string**, no como cuerpo. Lo largo (decisiones, planes) va en
  `body.raw = {{$var:<nodo>.response#campo}}`: un único campo del Extract con el JSON entero.
- Las variables se referencian por el `persistent_id` del nodo origen ⇒ se crea nodo a nodo.
- Antes de publicar se fija `custom-output` en cada nodo: publicar lanza un test-all que **enviaría el email**.
- Una URL puede empezar por variable (`{{callback_base}}/perceptions`).
- El `run_id` de una llamada web no existe en HR hasta que alguien entra en la sala.

## Los dos contratos (mismo estado)

**Kernel** (bearer): `POST /perceptions` · `GET /state?crisis_id=&format=string|json` · `POST /decisions`.
**Gateway** (bearer): `GET /api/snapshot?run_id=` · `POST /api/commands` con
`{command_id, run_id, command_type, expected_plan_version?, payload|payload_json}` → 200 · 200 `duplicate:true` ·
409 si `expected_plan_version` no es la vigente (solo `replace_plan`) · 422.
Ambos aceptan query string, cuerpo JSON o mezcla, y tipos laxos (`"false"`, arrays como string).

## API para el dashboard

| Pantalla | Endpoint |
|---|---|
| Inicio | `GET /crises?status=active` |
| Alta (texto libre + dictado) | `POST /crises/draft` `{text}` → `{spec{…, reports[]}, risk[], missing[], assumptions[], blocking, parsed_by}` (no crea nada; `reports` = lo que el texto dice que ya pasa, `risk` = severidad y llegada por zona que se deduce), `POST /crises` acepta `reports[]` y los siembra como primeros avisos del CECOPI (`core/declare.py::seed`), `POST /crises` `{pack?, name, region, scenario, zones[], sources[], resources[], transcript, source:"text"}`, `GET /stt?warm=1`, `POST /stt?lang=es&hint=` (cuerpo = la grabación) → `{text}` |
| Cabecera + KPIs + roles | `GET /crises/{id}` |
| Panel Coordinación / Autoridad / Respuesta | `GET /crises/{id}/overview?role=coordination\|authority\|responder&entity_id=` |
| Zonas (grafo + detalle) | `GET /crises/{id}/zones`, `/zones/{zona}` |
| Acciones | `GET /crises/{id}/actions?status=&actor=&zone=` → `{pending, log, counts}` |
| Señales | `GET /crises/{id}/signals?modality=&noise=&zone=&precise=`, `GET /crises/{id}/signals/stats` |
| Recursos | `GET /crises/{id}/resources?entity_id=` — los inventarios son **de cada entidad**: CECOPI (o sin `entity_id`) lo ve todo; cualquier otra entidad solo sus unidades y sus suministros. El mismo `entity_id` acota el KPI de Recursos en `GET /crises/{id}` y oculta las unidades ajenas en `/entities`. |
| Contactos | `GET /crises/{id}/directory`: las **entidades** con las que se puede comunicar (canal, destino, estado, escalado) y, colgando de cada una, todas sus comunicaciones con transcripción · `POST /crises/{id}/entities/{e}/contact {message, by}` inicia una comunicación por el canal de esa entidad · `GET /crises/{id}/contacts[/{c}]` sigue dando el registro plano |
| Plan | `GET /crises/{id}/plan` (plan vigente, historial con el porqué de cada cambio, incidentes) |
| Otros | `/tripwires`, `/entities`, `/lessons`, `/manuals`, `POST /crises/{id}/manuals/lookup` (Exa) |

Los ítems llevan la forma de los componentes del diseño: `ActionItem` ← `{action, time, verbLabel, actorName,
deadline}`, `SignalItem` ← `{signal, time, sourceName, noise}`. Swagger en `/docs`.

**Intervención humana**: `POST /crises/{id}/actions/{a}/approve|reject {by, note}` · `POST /crises/{id}/actions`
(botones "Tus capacidades"; pasa por la misma validación) · `POST /crises/{id}/signals` (nota del operador →
`PedroD-crisis-intake`) · `POST /crises/{id}/replan` · `POST /crises/{id}/clock {speed, paused}` ·
`POST /crises/{id}/sim/inject {kind: signal|road_cut|entity_unreachable|source_silent|hazard_jump|resource_loss}` ·
`POST /crises/{id}/close` (genera lecciones).

**Tiempo real**: `GET /crises/{id}/events` (SSE; `id` = seq, respeta `Last-Event-ID`, `?after=` para recuperar).
Tipos: `clock.tick`, `signal.created|updated`, `zone.updated`, `action.created|updated`,
`approval.requested|escalated|decided|stalled`, `contact.created|updated|transcript|unanswered`,
`tripwire.armed|fired`, `plan.replaced|invalidated`, `brain.wake|result`, `entity.updated`, `resource.updated`,
`sim.event`, `hr.error|fallback`, `lesson.created`. El payload es el objeto completo: upsert por id.

**Voz** (el navegador entra en la sala con `livekit-client` usando `{url, token}`; la API key no sale del backend):
- Contacto de voz `ringing` en `overview.ringing` → `POST /crises/{id}/contacts/{c}/answer` → `{url, token, room_name, run_id}`.
- Supervisión: `.../listen` (oyente oculto) · `.../takeover` (el agente se retira) · `.../hangup` · `.../ended`.
- Declarar crisis por voz: `POST /voice/crisis-start/token` y al colgar `POST /voice/calls/{run_id}/finish {kind:"crisis-start"}`.
- Ciudadano llamando al 112: `POST /voice/emergency-call/token` y al colgar `.../finish {kind:"emergency-call", crisis_id}`
  (la transcripción entra como señal por `PedroD-ingest-calls`).
- Aprobación por email: el correo lleva enlaces `/a/{token}`; el GET solo muestra un botón (los antivirus
  pre-cargan enlaces) y el POST decide.

## Escenario y aprendizaje

Cada crisis tiene **su propio guion** (`GET /crises/{id}/timeline`): «Riada en Paiporta» usa el escrito a mano
(`valte/sim/packs/riada-paiporta.json`, se regenera con `scripts/build_pack_riada.py`: 6 zonas con retardos, 28 entidades,
suministros y 150 min con ruido, un aforo que enmudece, una entidad que deja de contestar, un puente hundido, una residencia con
50 personas y pérdida de bombas). Cualquier otra —incendio, apagón, fallo de infraestructura, víctimas múltiples, sobre las zonas
que se describa al declararla— recibe uno generado por `valte/sim/generator.py` a partir de su grafo de zonas y sus retardos, estable por
crisis. A esas crisis se les añaden las fuentes mínimas (112, sensores, medios, redes), un reflejo de silencio de sensores y una
entidad de refuerzo (`ume`).

Quién reproduce el guion: el propio kernel, o la app **Mundo exterior** (`simulator/`) cuando la crisis tiene
`external_feed: true` (`POST /crises/{id}/feed`). Los datos entran por `POST /crises/{id}/inputs` (texto → percepción en
HappyRobot; lectura de sensor → señal directa) y los imprevistos por `POST /crises/{id}/sim/inject`. El simulador nunca escribe
lo que el sistema debe *descubrir*: el silencio lo detecta un tripwire; que alguien no contesta se sabe al llamarle.

Decisión continua: el estado que lee el cerebro incluye `open_needs` (avisos graves que nadie atiende aún) y `resource_board`
(unidades libres y desplegadas por zona). Un reflejo permanente (`tw-triaje-rescate`) despacha 2 unidades en el acto ante un aviso
de severidad ≥ 8 con ubicación de calle; el coordinador refuerza o reasigna después. Las llamadas a una misma entidad se encolan:
una persona atiende una llamada cada vez.

Al cerrar una crisis se guardan lecciones en castellano (fiabilidad real de cada fuente, quién no contesta, latencia de
aprobaciones, minutos hasta avisar aguas abajo) que ajustan los priors y se inyectan en el estado de la siguiente crisis del mismo
tipo. Lo que ve el supervisor: `overview.changes` («últimos cambios», una línea por cosa que altera el cuadro) y `GET /plan`
(objetivos, incidentes, por qué murió cada plan — con los motivos ya traducidos).

## Incidencias: una o varias señales son una incidencia

Lo que ve el supervisor, lo que priorizan los cerebros y lo que atienden los reflejos ya no son señales sueltas sino
**incidencias** (`valte/core/incidents.py`, sin LLM ni créditos): al llegar cada señal el kernel la archiva en la incidencia de la
que habla o abre una. Misma zona, mismo tipo de problema (personas en peligro, vía cortada, sin suministro, daños en edificio,
albergue, ofrecimiento de ayuda o la amenaza general de la zona) y, donde el punto concreto distingue dos trabajos, el mismo
punto (coincidencia de palabras del lugar; un aviso con precisión de calle pero sin lugar nunca se fusiona: un rescate doblado
cuesta menos que uno perdido). Cinco llamadas sobre la misma residencia = una incidencia, un reflejo, una necesidad.

- **Cuánto creerla**: cuenta **fuentes independientes**, no mensajes (cada llamante del 112 es una; todas las redes sociales son
  una: un reenvío no es un testigo). Una sola voz sin verificar es `candidate` («sin confirmar», nunca P0): se verifica o se
  prepara algo reversible, no se le comprometen unidades escasas. La confianza de cada señal usa la misma regla.
- **Estados**: `candidate` → `active` (creíble, nadie encima) → `attended` (una acción *en su zona* la cita: sus señales o su
  `inc-…`) → `resolved` (las acciones terminaron, o la amenaza remitió) · `dismissed` (una persona dice que es falsa: se retiran
  las aprobaciones pendientes y sus fuentes quedan apuntadas) · `merged`. Si quien la atendía falla o es rechazado, vuelve a ser de nadie.
- **Menos despertares**: un aviso que solo repite lo que su incidencia ya dice es evidencia, no noticia: no despierta a ningún cerebro.
- `state.situation.incidents` / `snapshot.incidents` y `open_needs` van por incidencia. `crisis-command` ya no inventa
  incidencias: las re-prioriza por id, dice por qué importan, fija `revisit_at`, cierra las que han pasado y puede **fusionar**
  dos que son el mismo suceso (`{"merge": [["inc-0003","inc-0007"]]}`); las que omite siguen como están.
- API: `GET /crises/{id}/incidents?state=&zone=&entity_id=` → `{counts, incidents[], noise[]}` · `GET …/incidents/{iid}` (con sus
  señales y acciones) · `POST …/incidents/{iid}/dismiss {by, reason}` · `POST …/incidents/{iid}/merge {into, by}`. `overview` trae
  `incidents[]` y los KPIs `incidents{open, unattended, candidate…}`. Eventos `incident.opened|updated|dismissed|merged`.
  Las crisis anteriores al modelo reciben sus incidencias de sus señales en el primer tick.

## Lecciones: dentro de una crisis y de una a la siguiente

`valte/core/learning.py`. Dos reglas: una lección **cita evidencia** (ids reales de acciones, contactos, incidencias o señales) o
no se guarda, y toda decisión que se apoya en una lección **lo dice** (`lesson_uses`; los cerebros añaden `"lessons": ["L-12"]` a
la acción o al plan, el kernel descarta los ids inventados).

- **Dentro** (`learn_now`, cada 5 ticks): lo que las propias decisiones se han encontrado se aplica *ya*. Quién no contesta (≥2
  contactos sin respuesta → la siguiente firma se pide a su escalado sin esperar al timbre) · cuánto tarda cada autoridad en
  firmar, en minutos de escenario · lo que una persona rechazó (la misma orden en la misma zona sin una señal posterior al
  rechazo la rechaza el kernel citando la lección) · fuentes que dieron falsas alarmas (≥2 incidencias descartadas → su
  fiabilidad baja en el acto) o que avisaron primero y acertaron · cuánto esperan las incidencias graves. Más lo que diga una
  persona: `POST /crises/{id}/lessons {text, by}`. Entran en `state.lessons` con id, `learned: in_this_crisis` y su evidencia.
- **Entre crisis** (`close_crisis` → `carry_forward`): lo aprendido pasa a `scope: global` para las siguientes del mismo tipo.
  Vista otra vez gana peso («vista en 2 crisis»); desmentida por los hechos lo pierde y se retira. Al abrir, `apply_lessons`
  mueve los priors y lo deja anotado. Tras el cierre, `PedroD-crisis-review` (webhook → Extract, en segundo plano) propone hasta
  4 lecciones cualitativas; solo se guardan las que citan evidencia que existe.
- `GET /crises/{id}/lessons` → `{now[], before[], applied}` con evidencia y usos de cada una.

## Canal de incidencias

Quien está sobre el terreno le cuenta al sistema lo que ve: `POST /crises/{id}/reports {by, kind, name}`
(`GET /crises/{id}/reports?by=` lista los tipos y las incidencias). Basta un **nombre y un tipo**: del nombre salen la zona (la
que menciona; si no, el municipio de quien reporta; si no, la zona peor parada de su ámbito), el punto concreto, el recurso
(«perdemos 4 bombas de achique») y las cantidades (en cifra o en letra; el 36 de «CV-36» no cuenta). Quien llame por script puede
seguir fijándolos: `zone?, place?, resource?, qty?, units?, severity?` (`text` = `name`). Solo reportan autoridades y unidades de
respuesta de la crisis —también el CECOPI—, y un ayuntamiento solo sobre su jurisdicción. Cada incidencia entra como **señal fiable** del propio
actor (la ven las necesidades abiertas, los reflejos y los dos cerebros) y aplica sus consecuencias en el acto
(`valte/core/reports.py`):

| `kind` | Repercusión |
|---|---|
| `road_cut` | La zona queda con acceso cortado: +15 min (hasta 45) para quien entra desde fuera —gana el recurso local en la asignación— y las unidades enviadas tardan eso más en quedar libres. Invalida el plan. |
| `people_trapped`, `building_damage` | Necesidad abierta de máxima prioridad; el nombre hace de punto concreto, así que el reflejo de triaje despacha 2 unidades sin esperar al LLM. |
| `resource_lost` | Descuenta del inventario del propietario (no se puede reportar sobre material ajeno; sin cantidad, se pierde todo; si el nombre no deja claro qué recurso es, responde 422 con los que hay). |
| `units_down` | Descuenta unidades propias, libres y totales. |
| `shelter_full` | Plazas de albergue de la zona a cero. |
| `power_out`, `other` | Zona marcada / aviso fiable para el agente. |

Por el **mismo canal y con los mismos dos campos** se cuenta lo que ha **cambiado**, no solo lo que se ha roto (`core/changes.py`).
El plan siempre va por detrás de la calle; esto es la calle corrigiéndolo. Solo autoridades y unidades de respuesta —un vecino da
pistas, no hechos— y nada se salta las reglas del kernel:

| `kind` | Qué escribe quien reporta | Qué hace el kernel |
|---|---|---|
| `zone_new` | «se ha roto la mota y ahora se inunda Sedaví, 10.500 habitantes, llega en 25 min» | La zona entra en el mapa aguas abajo de la de quien avisa (el retardo del texto, o 20 min supuestos y dicho), con su ayuntamiento y sus vecinos; quien ya cubría toda la crisis la cubre también; se geocodifica en segundo plano y entra como aviso localizado, así que arranca con severidad, cuenta atrás e incidencia. |
| `resource_new` | «nos llegan 200 mantas y 4 bombas de achique» · «solo quedan 3 bombas» | Suma al inventario de quien avisa (el CECOPI puede sobre el de cualquiera) o **corrige** la cuenta si el texto dice «solo quedan / en realidad / corrijo». Lo que no existe se crea. |
| `entity_new` | «se suma Cruz Roja Valencia con 12 voluntarios para rescate y 2 embarcaciones» | Alta como unidad de respuesta con sus unidades, su material a su nombre y las capacidades que digan sus palabras (rescate, achique, albergue, suministros; por defecto solo comprobar). Fiabilidad media: la avala una persona del dispositivo, no es un organismo oficial. |
| `action_done` | «ya hemos cortado el puente de la CV-36 por nuestra cuenta» | Queda como acción **suya ya ejecutada** (`origin: human`), con el mismo control de capacidades, jurisdicción y duplicados que si la propusiera el agente: si no puede hacerlo, se le dice; si ya estaba, se le dice. El agente deja de pedirla y cuenta con ella. |

De estos cuatro, solo `zone_new` genera señal e incidencia: la logística no es una incidencia, cambia el mundo y se cuenta en el
digest. Todo lo que hubo que suponer (la zona de la que cuelga, el retardo, el dueño del material) se devuelve escrito en `effects`.

El coordinador despierta con un resumen de lo ya aplicado. En el dashboard: botón **⚑ Reportar incidencia** en los tres paneles de rol
(Coordinación, Autoridad y Respuesta; `?report=1` lo abre directamente) con un formulario de dos campos, nombre y tipo, línea propia en «Últimos cambios» y aviso en Señales firmado por la entidad.

## Probar

```bash
uv run pytest                                        # núcleo, API, incidencias, lecciones, cambios de mundo y supervisión, sin red (81 tests)
VALTE_BRAIN=local VALTE_OUTREACH_MODE=dry VALTE_DB_URL=sqlite:////tmp/valte-smoke.db scripts/dev_server.sh 8011
scripts/smoke.sh localhost:8011                      # API de punta a punta, sin gastar créditos
scripts/reset_demo.sh                                # borra las catástrofes y reinicia kernel + mundo para ensayar otra vez
uv run python scripts/reset_db.py                    # limpia el mundo, conserva el registro de workflows
uv run python scripts/delete_crisis.py VLC-1234      # borra una crisis (un ensayo) y las lecciones que dejó
uv run python scripts/delete_crisis.py --all         # todas las catástrofes; las lecciones globales se quedan
nohup scripts/tunnel_watch.sh 8010 > /tmp/valte-tunnel-watch.log 2>&1 &   # reabre el túnel cuando caduca
```

Cada run del coordinador cuesta ~1 crédito: los despertares van con debounce (2 s), intervalo mínimo (8 s),
single-flight y tope por crisis; `crisis-command` solo despierta cuando cambia la huella material del plan.
Un ensayo contra HappyRobot gasta ~10 créditos por minuto real a 20–30×.

## Verificado en vivo contra HappyRobot / pendiente

Verificado: ingestión (3 canales) con callback por túnel en ~4 s · coordinator decidiendo con cuerpo raw ·
`crisis-intake` (nota de operador → señal) · `crisis-command` (plan con incidentes y objetivos) ·
`crisis-response-coordination` (interpretó una aprobación que la regla local no entendía) · emisión de tokens de voz ·
aprovisionado idempotente y ruta de actualización (fork → nodos → publish).

Pendiente de comprobar con una persona delante: email real (`DEMO_EMAIL_TO` vacío hasta ahora) y que los datos
del aviso (`data` del token) lleguen como variables al primer mensaje de `PedroD-outreach-call` (solo se ve
entrando en la sala desde el navegador).
