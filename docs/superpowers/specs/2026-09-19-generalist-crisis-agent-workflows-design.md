# Diseño del sistema generalista de coordinación de crisis

**Estado:** aprobado para especificación
**Fecha:** 2026-09-19
**Escenario principal:** DANA/inundación inspirada en Valencia 2024, con hechos operativos ficticios
**Ámbito:** demo de hackathon sobre HappyRobot, Supabase y Azure Static Web Apps

## 1. Resumen ejecutivo

El sistema recibe información incompleta y contradictoria sobre una crisis, la convierte en incidentes operables, mantiene un plan global, coordina acciones reales controladas y replantea la respuesta cuando cambian las condiciones.

La solución es generalista. DANA es el Scenario Pack más completo y la historia de la demo, pero el núcleo no contiene reglas, verbos ni estructuras exclusivas de inundaciones. La generalidad se demuestra ejecutando además cinco packs mínimos: incendio forestal, apagón regional, fuga química, terremoto y crisis humanitaria/logística.

Las responsabilidades principales son:

- **HappyRobot:** conversación, extracción, razonamiento y coordinación multicanal.
- **Supabase:** fuente de verdad, estado, reloj, concurrencia, reservas, eventos y Realtime.
- **Azure Static Web Apps:** dashboard operativo y Functions HTTP cortas.
- **Scenario Controller:** evolución determinista de la simulación y custodia de la verdad oculta.
- **Transactional State Gateway:** único escritor del estado autoritativo.

Los tres workflows generalistas son `crisis-intake`, `crisis-command` y `crisis-response-coordination`. Se comunican mediante contratos versionados y eventos persistidos; no se llaman entre sí mediante esperas largas ni comparten estado en memoria.

## 2. Objetivos y criterios de éxito

La demo debe probar, de extremo a extremo:

1. Ingesta de llamadas, mensajes o webhooks con ruido y datos incompletos.
2. Separación entre observaciones, creencias operativas y verdad del simulador.
3. Priorización de incidentes simultáneos y asignación de un recurso escaso.
4. Planificación multietapa con acciones inmediatas, paralelas, diferidas y contingencias.
5. Al menos una interacción externa real y controlada mediante HappyRobot.
6. Replanificación cuando cambia una ruta, un recurso o el resultado de una misión.
7. Aprobación humana para acciones de alto impacto.
8. Trazabilidad desde una acción hasta su evidencia, plan, ejecución y outcome.
9. Dashboard que permita comprender e intervenir en el sistema.
10. Postmortem que compare lo observado y decidido con la verdad oculta.

El sistema responde repetidamente a las seis preguntas del track: qué información importa, qué va primero, a quién avisar, dónde asignar recursos, qué hacer ahora y cuándo abandonar un plan.

## 3. Fuera de alcance

Esta solución no pretende ofrecer:

- seguridad, autenticación, autorización o auditoría de nivel productivo;
- integración con 112 u otros servicios oficiales de emergencias;
- GIS avanzado, navegación real u optimización matemática de recursos;
- alta disponibilidad, operación multirregión o recuperación ante desastre;
- garantía `exactly-once` sobre llamadas, correos o mensajes externos;
- aprendizaje autónomo que modifique prompts, políticas o packs sin revisión;
- composición dinámica de varios Scenario Packs durante un run;
- cobertura de cualquier crisis imaginable;
- ejecución física real más allá de comunicaciones y respuestas de demo controladas.

La interfaz y todas las comunicaciones deben indicar que se trata de una **SIMULACIÓN** y que el sistema no sustituye a un centro de mando humano.

## 4. Arquitectura

```text
Fuentes / Web Voice / Chatbot / Simulator
                    │
                    ▼
        crisis-intake (HappyRobot)
                    │ comandos HTTP
                    ▼
      Transactional State Gateway
                    │ transacción
                    ▼
                Supabase
      estado + eventos + outbox + reloj
          │                       │
          │ Realtime              │ Event Router
          ▼                       ▼
    Dashboard /ops       crisis-command
                                  │ acciones validadas
                                  ▼
                      crisis-response-coordination
                                  │ llamadas/mensajes/respuestas
                                  └──────────► Gateway

Scenario Controller ──► Gateway ──► verdad oculta y estímulos
```

### 4.1 Azure Static Web Apps

Azure Static Web Apps Free aloja:

- `/ops`: dashboard principal;
- `/approve/:token`: aprobación o rechazo mediante enlace opaco;
- `/api/commands`: entrada única de mutaciones;
- `/api/event-router`: drenaje y despacho del outbox;
- adaptadores HTTP breves para callbacks y tokens.

Las Functions no mantienen estado en memoria, no esperan conversaciones y no usan SSE como canal de negocio. El navegador lee snapshots desde Supabase y se suscribe directamente a Realtime.

El navegador utiliza la clave pública de Supabase con acceso de lectura a las proyecciones de demo. Las mutaciones y la clave `service_role` permanecen en Functions; aunque no haya autenticación productiva, el cliente no obtiene permiso de escritura sobre el estado operativo.

### 4.2 Supabase

Supabase es la única fuente persistente de verdad. Mantiene:

- estado observable del run;
- reloj de escenario;
- datos privados del simulador;
- versiones y control de concurrencia;
- recursos y reservas;
- comandos idempotentes;
- eventos append-only y outbox;
- aprobaciones, intentos de entrega y outcomes;
- proyecciones leídas por el dashboard.

Realtime notifica cambios, pero no garantiza orden ni completitud. El orden autoritativo procede de `state_version`, secuencias persistidas y snapshots.

### 4.3 HappyRobot

HappyRobot ejecuta los tres workflows. Los workflows leen un snapshot observable, razonan o conversan y solicitan cambios mediante `/api/commands`. No escriben directamente en tablas de negocio.

Se evoluciona el workflow existente `emergency-call` hacia `crisis-intake`, preservando su versión anterior. Se crean `crisis-command` y `crisis-response-coordination`. Los workflows `Random Yes No Endpoint` y `prueba-pedrodl-pe` quedan fuera de alcance y no se modifican.

Todo se ejecuta en el entorno `development`.

### 4.4 Scenario Controller

El Scenario Controller:

- valida y carga un Scenario Pack;
- crea el run y controla el reloj simulado;
- emite los estímulos programados;
- evoluciona hazards, rutas y dependencias ocultas;
- aplica efectos simulados solo tras outcomes confirmados;
- detiene, pausa, reanuda o completa la simulación;
- revela la verdad oculta exclusivamente en el postmortem.

No prioriza incidentes ni decide acciones en nombre del agente.

## 5. Workflows de HappyRobot

### 5.1 `crisis-intake`

**Propósito:** convertir una interacción o payload de origen en señales estructuradas, versionadas y trazables.

Entradas:

- sesión Web Voice, PSTN si está disponible o Chatbot;
- webhook de sensor, simulador u otra fuente;
- texto, transcript, ubicación declarada, modalidad y procedencia;
- identificador de sesión/evento y, cuando exista, `crisis_id`.

Una sesión conversacional inicia Intake directamente y persiste sus revisiones mediante el Gateway. Una entrada estructurada se registra primero como `source_input.received` y el Event Router inicia Intake. Ambos caminos convergen en el mismo contrato Signal e idempotencia.

Proceso:

1. Deduplica la entrada.
2. Conserva el contenido y la procedencia originales.
3. Extrae claims sin presentarlos como hechos confirmados.
4. Separa contenido relevante de ruido.
5. Calcula `content_fingerprint`, enlaza derivaciones conocidas y asigna un cluster de procedencia.
6. Resuelve ubicación con Locate/Maps si está disponible o con el catálogo local de zonas.
7. Expresa precisión, confianza, independencia, contradicciones y necesidad de verificación.
8. Durante una llamada publica una observación provisional.
9. Al finalizar revisa el transcript completo y publica una revisión final.

La idempotencia de las revisiones usa `report_id:revision`. Cada revisión es inmutable y puede quedar `active`, `superseded` o `retracted`. Una revisión final puede corregir o retirar una observación provisional sin borrar su historial ni cambiar retrospectivamente lo que el sistema conocía.

Si solo existe un reporte crítico no verificado, Intake puede provocar verificación urgente, preparación reversible y solicitud de aprobación; nunca autoriza por sí mismo un despliegue.

Salida: una `Signal` creada o revisada, con evidencias y confianza explicable. Intake no crea planes, no reserva recursos y no ejecuta acciones.

Cuando una entrada no contiene `crisis_id`, se asocia automáticamente solo si existe un único run activo compatible; en cualquier otro caso queda en `needs_review`.

### 5.2 `crisis-command`

**Propósito:** mantener un único plan global y versionado por crisis.

El workflow contiene dos pasos de razonamiento:

1. **Situation Analyst:** resume hechos observables, incertidumbres, tendencias, contradicciones y cambios respecto al plan anterior.
2. **Commander:** ordena objetivos y propone un portfolio de acciones.

El plan no es una lista lineal. Debe incluir:

- incidentes ordenados;
- asignaciones vigentes;
- acciones inmediatas, paralelas y diferidas;
- tareas de verificación;
- contingencias;
- supuestos y condiciones de revisión;
- para todo incidente activo, una acción actual, una verificación o una razón explícita con `revisit_at`.

La prioridad combina amenaza vital, tiempo hasta el daño, personas afectadas, vulnerabilidad, confianza, tendencia, precisión de ubicación, tiempo de llegada, encaje del recurso y reversibilidad. HappyRobot explica el orden, pero no produce una puntuación numérica con falsa precisión. `entity.weight` es un prior de autoridad, no una prioridad de incidente. Cada Incident, Plan y Action conserva referencias a las revisiones exactas de evidencia utilizadas.

Las propuestas pasan por validación determinista de:

- evidencia disponible;
- capacidad, jurisdicción y estado del actor;
- unidades y reservas;
- ruta operativa;
- integración y destinatario permitidos;
- política de riesgo y aprobación;
- HumanDirective activas y su precedencia;
- `state_version` y versión del plan.

El asignador elige solo entre candidatos válidos usando prioridad, disponibilidad, demora de activación, ajuste de capacidad y un desempate estable por identificador. La acción y su reserva `held` se confirman atómicamente mediante el State Gateway; el modelo no puede saltarse el ledger de reservas.

Si una propuesta no es válida, se permite una sola reparación razonada. Un segundo fallo la deja en `needs_human_review` sin efecto lateral.

Solo puede existir un Commander activo por run. Los eventos recibidos durante su ejecución marcan el run como `dirty`; al terminar se ejecuta una única revisión adicional si sigue siendo necesaria.

### 5.3 `crisis-response-coordination`

**Propósito:** ejecutar y seguir de forma asíncrona las acciones ya validadas.

Proceso:

1. Revalida que el run siga activo, además de la vigencia del plan, aprobación y reserva.
2. Solicita al Gateway `authorize_external_effect`. Solo si el run sigue activo, el Gateway persiste el intento con `dispatch_id`, `dispatch_authorized_at` y `authorized_state_version` antes del efecto externo.
3. Selecciona el primer canal disponible de la cadena autorizada.
4. Envía la misión marcada como `SIMULACIÓN` a un destinatario en whitelist.
5. Registra entrega, aceptación, rechazo, ejecución, timeout o incertidumbre.
6. Convierte nueva información obtenida en otra Signal, sin reescribir el pasado.
7. Solicita replanteamiento cuando cambia una capacidad, respuesta, deadline o resultado.

La aceptación o el inicio de la misión convierte su reserva `held` en `committed`. Un rechazo o fallo confirmado antes del despliegue la libera. Un resultado `unknown` la convierte en `quarantined` hasta reconciliación humana.

No mantiene esperas largas dentro del workflow. Los deadlines se registran como `due_scenario_at` y el Scenario Controller/Event Router despierta el siguiente paso cuando corresponde.

Si se sabe que no hubo efecto y la acción es de bajo riesgo, se permite un reintento limitado. Si no puede saberse si el efecto ocurrió, el estado pasa a `unknown`, se detiene la cadena y se requiere reconciliación humana. Nunca se reintenta a ciegas un efecto externo de alto impacto.

## 6. Contratos de dominio v2

El contrato estable del núcleo es:

```text
Signal → Incident → Plan → Action → Outcome
```

Todos los objetos v2 incluyen:

- `contract_version`;
- identificador propio y `run_id`;
- `pack_id`, `pack_version` y `pack_digest`;
- `scenario_at`, `received_at` y, cuando proceda, `processed_at`;
- procedencia estructurada;
- `correlation_id` y `causation_id`;
- revisión o versión cuando sean mutables.

`run_id` identifica un run del escenario. Una ejecución de HappyRobot se identifica siempre como `workflow_run_id` o `dispatch_id`.

Cada run de la demo contiene exactamente un agregado de crisis. `crisis_id` identifica ese agregado dentro del dominio y `run_id` es la frontera de persistencia, reloj y concurrencia; por tanto, solo hay un plan global y un Commander activo por run.

### 6.1 Signal

Una Signal es evidencia observable, no ground truth. Contiene contenido original, claims, fuente, modalidad, ubicación, precisión, confianza, procedencia y revisión. Distingue el prior `source_trust_snapshot` de la confianza calculada `signal_confidence`. Sus revisiones son append-only; `superseded` significa reemplazada por información más reciente y `retracted` significa que sus claims ya no deben sustentar decisiones activas.

Su procedencia incluye `reporter_id`, `origin_reference` cuando se conoce, `derived_from_signal_id`, `content_fingerprint`, `source_cluster_id` e `independence_status`. Este último puede ser `confirmed_independent`, `likely_same_origin` o `unknown`.

### 6.2 Incident

Un Incident es una hipótesis operativa derivada de una o más señales. Puede relacionarse con varios hazards o fallos de dependencia. Conserva prioridad, confianza, zonas afectadas, evidencia, estado y `revisit_at`.

### 6.3 Plan

Un Plan es una revisión coherente y global. Incluye `plan_version`, objetivos, supuestos, incidentes cubiertos, acciones y `supersedes_plan_id`. Solo una revisión puede estar activa por crisis.

### 6.4 Action

Una Action es una intención operativa concreta vinculada a un plan. Incluye actor, capacidad, objetivo, parámetros validados, evidencia, razonamiento, prioridad, reserva, riesgo y política de aprobación.

Su ciclo de vida es:

```text
proposed
  ├─ pending_approval → approved
  └─ approved
approved → dispatching → delivered ───────────────→ completed
                              └─→ accepted → executing → completed
```

Las acciones unidireccionales, como un aviso cuya entrega se confirma, pueden completar desde `delivered`. Las misiones que requieren compromiso del receptor pasan por `accepted` y `executing`. Salidas alternativas: `rejected`, `timed_out`, `unknown`, `failed` y `canceled`.

`approved` significa que la acción ha superado su política: automáticamente si es reversible y de bajo riesgo, o mediante decisión humana si es de alto impacto. La aprobación se conserva además como registro separado para auditoría.

Una acción P2/P3 sin iniciar puede preemptarse automáticamente. Preemptar o redirigir una P0/P1, o cualquier acción ya iniciada, requiere aprobación humana.

Las evidencias son referencias tipadas a Signal, Incident, Outcome o HumanDirective; no se limitan a IDs de señales. Una referencia a Signal incluye siempre `signal_id` y `revision`, nunca solo el identificador estable.

### 6.5 Outcome

Un Outcome es append-only y representa el resultado de un intento: éxito, resultado parcial, fallo conocido, ausencia de respuesta o resultado incierto. Una observación nueva genera otra Signal en vez de modificar retrospectivamente el Outcome.

## 7. Modelo persistente

El modelo lógico incluye:

- `scenario_runs`: pack, estado, reloj, velocidad, versión global y motivo de cierre;
- `zones`, `impact_edges`, `routes` y `dependency_edges`;
- `entities` y `resources`, con `resources` como único ledger de capacidad y modo `reusable` o `consumable`;
- `resource_reservations`, vinculadas a acción, unidades, estado y expiración;
- `signals`, `signal_revisions`, `source_clusters`, `signal_provenance_links`, `incidents`, `incident_signals` y `evidence_dependencies`;
- `plans`, `actions`, `approvals`, `action_attempts` y `outcomes`;
- `human_directives` con razón y expiración;
- `commands`, `events` y `outbox`, con carril de prioridad, clave de lote, disponibilidad y lease;
- `late_external_events`, append-only y separados del estado operativo cerrado;
- `orchestration_state` y `workflow_dispatches`;
- `scenario_truth`, incluidos hazards y estados reales de rutas, en acceso privado.

Los grafos son independientes:

- **impact:** propagación o exposición;
- **mobility:** desplazamiento, tiempo, capacidad, estado y tipos de recurso permitidos;
- **dependency:** relación funcional entre servicios, activos o recursos.

Una arista nunca adquiere semántica de otra capa. El mapa es esquemático y no ofrece navegación real.

### 7.1 Lifecycle de reservas

Una reserva conserva `reservation_id`, `action_id`, `resource_id`, unidades, `status`, `held_at`, `expires_at_scenario`, timestamps de transición, razón de liberación y versión.

```text
held ───────────────→ committed ──→ released | consumed
  ├─→ released           └────────→ quarantined
  ├─→ expired
  └─→ quarantined ──human──→ committed | released | consumed
```

- `held`: el plan ha apartado el recurso, pero la misión todavía no ha comenzado. Incluye expiración en tiempo de escenario.
- `committed`: el actor aceptó o inició la misión. No expira automáticamente.
- `released`: el recurso vuelve a estar disponible, con una razón explícita.
- `consumed`: las unidades consumibles se descuentan definitivamente tras un Outcome confirmado.
- `expired`: la acción no obtuvo aprobación o no comenzó dentro del plazo configurado.
- `quarantined`: no se puede determinar si el recurso fue desplegado; no está disponible hasta reconciliación humana.

La suma de reservas activas (`held`, `committed` y `quarantined`) nunca puede superar la capacidad del recurso. La restricción se valida dentro de la misma transacción que crea o cambia la acción.

Reglas de transición:

- `pending_approval` y `approved` antes del despacho mantienen `held`.
- `accepted` o `executing` convierten la reserva en `committed`.
- rechazo, cancelación, supersession o preemption antes del efecto producen `released`.
- vencer `expires_at_scenario` antes de comenzar produce una reserva `expired`, una Action `timed_out` y activa replanteamiento.
- un fallo conocido sin despliegue produce `released`.
- `completed` produce `released` para un recurso reutilizable o `consumed` para unidades consumibles, según el Outcome y el Action Catalog.
- `unknown` desde `held` o `committed` produce `quarantined`; ni el agente ni un timeout pueden liberarla automáticamente.
- `timed_out` libera solo cuando existe confirmación de que el actor no aceptó ni empezó; en caso contrario debe clasificarse como `unknown`.

Cada entrada del Action Catalog que usa recursos declara `reservation_ttl_scenario` y su disposición al completar: liberar un recurso reutilizable o descontar unidades consumibles. Una P2/P3 no iniciada puede liberar o transferir su reserva por preemption; una P0/P1 o reserva `committed` requiere aprobación.

### 7.2 Retractación de evidencia

`evidence_dependencies` mantiene el índice desde una revisión concreta de Signal hasta los Incident, Plan, Action y Approval que la utilizaron. Cada Action mantiene además `evidence_status`: `valid`, `needs_reassessment` o `invalidated`. El comando `retract_signal_revision` ejecuta en una única transacción:

1. cambia la revisión `active` a `retracted` y registra la revisión final que la sustituye, si existe;
2. marca los Incident dependientes como `needs_reassessment`;
3. bloquea nuevas autorizaciones de las Action dependientes con `evidence_status=needs_reassessment`;
4. reevalúa las reglas de evidencia de `policies.json` usando únicamente revisiones todavía activas;
5. cancela las Action sin `dispatch_authorized_at` cuya evidencia restante resulte insuficiente, establece `evidence_status=invalidated` y libera sus reservas;
6. marca como `superseded` las Approval pendientes de esas acciones invalidadas;
7. marca las Action autorizadas o iniciadas con evidencia insuficiente como `evidence_status=invalidated` sin fingir que el efecto desapareció;
8. añade un evento `evidence.retracted` y el trabajo de replanteamiento al outbox.

Si las evidencias activas restantes todavía cumplen la policy, Command puede revalidar la Action dentro de una nueva revisión del plan y devolver `evidence_status` a `valid`; la retractación no la cancela automáticamente.

Para una Action ya autorizada:

- si todavía no produjo un efecto externo, Coordination la cancela y libera la reserva;
- si el efecto es reversible y el canal admite cancelación, crea un intento de cancelación trazable;
- si fue aceptada o está `executing`, detenerla o redirigirla requiere la política de aprobación aplicable a una acción iniciada;
- si está `completed`, no se modifica: el postmortem mostrará que se decidió con evidencia posteriormente retirada.

Una retractación nunca borra Signals, planes, acciones, outcomes ni mensajes ya emitidos.

### 7.3 Clusters de procedencia

Los clusters representan hipótesis de origen común, no incidentes ni claims. Una Signal siempre conserva su identidad aunque comparta cluster con otras.

Reglas de agrupación:

- el mismo identificador externo o payload exacto se trata como duplicado idempotente;
- una referencia explícita al mismo mensaje, URL, grabación o sensor asigna el mismo `source_cluster_id`;
- contenido casi idéntico con claims, tiempo y localización compatibles puede proponer `likely_same_origin`;
- la IA puede sugerir una agrupación, pero debe registrar razones y no puede declarar por sí sola `confirmed_independent`;
- `confirmed_independent` requiere procedencia observable que demuestre un origen distinto, como sensores independientes o sesiones de llamada separadas cuyos reporteros declaran observación directa; la mera ausencia de un enlace conocido conserva `unknown`;
- `unknown` aumenta la necesidad de verificación, pero no cuenta como corroboración independiente para acciones de alto impacto.

La confianza y las policies cuentan clusters independientes, no el número bruto de Signals. Veinte copias de un rumor pertenecientes al mismo cluster aportan una sola procedencia. El prior de confianza de cada reportero sigue visible, pero no multiplica el origen subyacente.

Una agrupación puede corregirse mediante merge o split versionado. `source_cluster.merged` o `source_cluster.split` recalcula la confianza de las Signals afectadas y reutiliza `evidence_dependencies` para marcar decisiones `needs_reassessment`. Si deja de cumplirse la policy de evidencia, se aplica la misma cancelación segura y liberación de reservas que en una retractación. Nunca se eliminan las Signals originales.

## 8. Transactional State Gateway

Toda mutación usa:

```json
{
  "command_id": "...",
  "run_id": "...",
  "pack": {
    "id": "wildfire-minimal",
    "version": "1.0.0",
    "digest": "sha256:..."
  },
  "expected_state_version": 17,
  "actor": { "type": "workflow", "id": "crisis-command" },
  "command_type": "...",
  "payload": {},
  "causation_id": "..."
}
```

El Gateway procesa cada comando en este orden:

1. Busca `(run_id, command_id)`.
2. Si ya existe con el mismo fingerprint, devuelve el resultado original.
3. Si el mismo ID tiene otro contenido, responde `idempotency_mismatch`.
4. Comprueba que la identidad y el digest del pack coinciden con la snapshot inmutable del run; un desacuerdo devuelve `pack_context_mismatch`.
5. Comprueba que acciones, entidades, recursos y edges referenciados pertenecen a esa snapshot; una acción ajena devuelve `action_not_in_active_pack`.
6. Comprueba `expected_state_version`, schema, transición e invariantes.
7. En una sola transacción actualiza el dominio, añade eventos, crea outbox, guarda el resultado e incrementa `state_version` una vez.
8. Confirma la transacción antes de permitir un efecto externo.

Un conflicto de versión no modifica el estado. El cliente relee, recalcula y usa un nuevo `command_id`.

Una vez que el run alcanza `completed` o `aborted`, el Gateway activa un terminal fence. Cualquier comando que intente cambiar el estado operativo devuelve `run_closed`. La única escritura posterior admitida es el registro idempotente de un evento externo tardío en `late_external_events`, fuera de `state_version` y sin crear outbox operativo.

Propiedad semántica de las escrituras:

| Estado | Propietario de la decisión | Escritor físico |
| --- | --- | --- |
| Reloj y verdad oculta | Scenario Controller | Gateway |
| Señal normalizada | `crisis-intake` | Gateway |
| Incidentes, planes y acciones | `crisis-command` | Gateway |
| Intentos y outcomes | `crisis-response-coordination` | Gateway |
| Aprobaciones e intervención | Operador o token válido | Gateway |
| Eventos, outbox y versiones | Transacción aceptada | Gateway |

No existen escrituras directas desde HappyRobot ni desde el navegador.

## 9. Event Router y concurrencia

El Event Router consume el outbox con entrega `at-least-once`; la idempotencia está en el consumidor y en el Gateway. Reclama cada trabajo con lease y registra el `dispatch_id` antes de marcarlo como entregado.

Antes de cada dispatch vuelve a comprobar el estado del run. Si ya es terminal, no inicia el workflow y marca la entrada como `suppressed_run_closed`. Dentro de Coordination, ningún efecto externo puede ejecutarse sin una autorización persistida por el Gateway mientras el run estaba activo. Un efecto ya autorizado puede terminar después del cierre y no puede deshacerse; su respuesta posterior sigue el flujo de eventos tardíos.

Allowlist mínima:

| Evento | Destino |
| --- | --- |
| `source_input.received` | `crisis-intake` |
| `signal.created` / `signal.revised` | `crisis-command` |
| `evidence.retracted` | `crisis-command`, prioridad inmediata |
| `source_cluster.merged` / `source_cluster.split` | `crisis-command` |
| `route.blocked` / `resource.unavailable` | `crisis-command` |
| `human_directive.activated` / `expired` / `superseded` | `crisis-command` |
| `action.approved` | `crisis-response-coordination` |
| `mission.rejected` / `timed_out` / `failed` / `unknown` | `crisis-command` |

`plan.proposed`, `action.proposed` y `message.sent` no disparan al Commander. Esta exclusión evita bucles.

El Commander usa debounce de dos segundos de reloj real. El debounce no retrasa Intake ni una acción ya aprobada. `active_dispatch_id`, `lease_until`, `dirty` y `debounce_until` garantizan un único Commander activo. Un lease expirado conserva `dirty=true` para permitir recuperación.

`evidence.retracted` omite el debounce normal si no hay Commander activo. Si ya existe uno, marca `dirty=true` y fuerza una única revisión adicional al terminar; nunca crea dos Commanders paralelos.

### 9.1 Backpressure y tormentas de señales

Persistir una entrada y activar un agente son pasos diferentes. Toda entrada única se registra antes de encolarse; una repetición con la misma clave de idempotencia devuelve el recibo anterior. Por tanto, reducir invocaciones nunca elimina evidencia ni altera su trazabilidad.

Cada entrada del outbox conserva `lane`, `batch_key`, `available_at`, secuencia, estado, intentos y lease. El Router selecciona primero el carril de mayor prioridad disponible y mantiene orden estable dentro de cada carril:

| Carril | Trabajo |
| --- | --- |
| `control` | stop, abort, pause, aprobaciones, directivas y retractaciones de evidencia |
| `outcome` | callbacks, fallos, estados `unknown` y cambios de rutas o recursos |
| `intake_live` | conversaciones activas y fuentes configuradas como críticas |
| `signal_batch` | webhooks, sensores y señales estructuradas normales |
| `maintenance` | polling, reconciliación y tareas auxiliares de postmortem |

Los carriles `control` y `outcome` no pueden quedar bloqueados detrás de una tormenta de señales. Los carriles inferiores progresan cuando existe capacidad y su antigüedad queda visible; no se descartan silenciosamente por sobrecarga.

Las entradas estructuradas compatibles se agrupan durante una ventana corta de reloj real por `run_id`, digest del pack, zona, afirmación pre-normalizada y huella de procedencia cuando esté disponible. Intake recibe un sobre con los IDs del lote, pero crea o revisa cada Signal con procedencia individual y determina después su `source_cluster`. Los duplicados exactos no generan una nueva invocación y los ecos con una procedencia ya conocida pueden compartirla. Una conversación activa, una fuente crítica y cualquier evento de `control` u `outcome` evitan el batching normal.

La concurrencia es acotada y configurable para la demo: un solo Commander por run, un pool pequeño de Intake y un pool pequeño de Coordination con serialización por acción y destino. Los carriles de fondo nunca pueden consumir la última capacidad reservada para `control` y `outcome`; si Commander ya está activo, un evento urgente usa `dirty` y la revisión adicional definida arriba en vez de abrir otro. Alcanzar el límite deja trabajo persistido como pendiente; no abre ejecuciones adicionales. La configuración efectiva se captura en el snapshot del run para que la prueba sea reproducible.

El outbox se drena al recibir un webhook, aceptar un comando, avanzar el reloj, completar un dispatch o reanudar un run; no requiere un proceso residente. Si la profundidad, antigüedad o retraso superan sus umbrales, el run marca capacidad `degraded` sin declararse `offline` ni perder entradas.

## 10. Reloj y ciclo de vida del run

`scenario_runs` es la autoridad del tiempo y conserva `scenario_now`, `status`, `speed` y `last_wall_tick`.

Estados:

```text
ready → running ⇄ paused → completed
                      └──→ aborted
```

- `Pause scenario` congela estímulos y timeouts simulados.
- Las respuestas externas que lleguen durante la pausa se registran, pero no avanzan el reloj.
- Las expiraciones de reservas también se congelan porque usan tiempo de escenario.
- `Stop external actions` bloquea nuevos efectos externos sin pausar la evolución simulada.
- `Abort` cierra el run y habilita el postmortem.

Los eventos programados usan `due_scenario_at` y solo se disparan en `running`. El run termina al alcanzar una condición del pack, su duración máxima o un aborto humano. El motivo distingue éxito, timeout y fallo técnico sin multiplicar estados de lifecycle.

La transición terminal es atómica y guarda como `terminal_state_version` la versión resultante, además de `closed_scenario_at` y `closed_at`. Esa versión fija el snapshot evaluable del run. Las entradas de outbox todavía no despachadas quedan suprimidas y no pueden obtener nuevas autorizaciones de efecto externo. Los intentos autorizados antes del fence permanecen visibles como in-flight y pueden originar un evento tardío.

Los callbacks recibidos después del cierre se deduplican por identificador del proveedor o fingerprint y responden con éxito una vez persistidos, evitando reintentos innecesarios. Conservan `run_id`, `action_id`, `dispatch_id`, procedencia, `received_at`, resumen y referencia al payload. No cambian Action, Outcome, reservas, plan ni puntuación, y no despiertan al Commander.

## 11. Autonomía, aprobación y supervisión

- Acciones reversibles y de bajo riesgo pueden aprobarse automáticamente.
- Acciones de alto impacto requieren aprobación humana.
- Un reporte crítico único y no verificado permite preparar, verificar y solicitar aprobación, pero no desplegar automáticamente.
- Después de una aprobación humana todavía se revalidan versión, recursos, destinatario y plan.
- P2/P3 sin iniciar pueden preemptarse automáticamente; P0/P1 o una acción iniciada requieren aprobación.

El dashboard usa un lease de operador de 60 segundos. Solo el operador con lease puede mutar desde `/ops`; observadores son read-only. Al expirar, otra persona puede pulsar `Take control`. El lease evita colisiones, no constituye autenticación.

Los enlaces `/approve/:token` son una vía separada: token aleatorio, opaco, de un solo uso, vinculado a acción, decisión, versión y expiración. GET solo presenta información mínima; POST decide. La primera decisión válida gana y no necesita el lease de `/ops`.

### 11.1 HumanDirective y precedencia

Una HumanDirective condiciona la siguiente decisión del Commander; no modifica directamente rutas, recursos, truth ni acciones. Contiene:

- tipo `constraint`, `priority`, `cancel`, `verify` o `replan`;
- scope `run`, `incident`, `action`, `resource` o `zone`, con su identificador;
- parámetros cerrados por tipo;
- `effective_state_version`;
- razón y autor de demo;
- `created_at` y `expires_at_scenario`;
- `supersedes_directive_id` cuando sustituye otra.

Estados: `active`, `rejected`, `expired` y `superseded`.

La precedencia es:

```text
1. Estado terminal e invariantes transaccionales
2. Seguridad, capacidad, jurisdicción y estado operativo observable
3. HumanDirective activa
4. Policies y objetivos no duros del Scenario Pack
5. Propuesta del Commander
```

Una directiva puede cambiar prioridades, imponer una restricción, solicitar verificación, pedir replanteamiento o iniciar una cancelación conforme a su policy. No puede duplicar recursos, utilizar rutas cerradas, inventar capacidades, alterar un run terminal ni saltarse la aprobación requerida para detener o redirigir una acción protegida.

El Gateway valida la directiva antes de activarla. Si contradice un invariante devuelve `directive_conflicts_with_invariant`. Si resulta incompatible con otra directiva activa devuelve `directive_conflict` y los IDs implicados. La directiva aceptada más reciente del mismo tipo y scope sustituye atómicamente a la anterior.

Crear, expirar o sustituir una directiva produce un evento de la allowlist y activa Command. La expiración usa tiempo de escenario y se congela durante `paused`. Commander debe enumerar en el Plan las directivas activas y explicar cómo las aplicó o qué condición de precedencia superior impide cumplirlas. El Gateway y el dashboard explican las directivas rechazadas antes de activarse.

Una corrección factual, como declarar una ruta abierta, no es una HumanDirective: debe entrar como evidencia o comando `update_edge` validado. Los enlaces de aprobación son también un mecanismo separado.

## 12. Dashboard

`/ops` es una sola pantalla operativa con:

- mapa esquemático de zonas, rutas y estado observable;
- incidentes P0–P3 y confianza;
- plan activo, versión, diff, supuestos y evidencia;
- revisiones de evidencia retractadas y decisiones dependientes pendientes de reevaluación;
- número de Signals frente a número de clusters independientes, con explicación de agrupaciones;
- recursos disponibles, reservados y en ejecución;
- reservas `held`, `committed`, `expired`, `quarantined` y `consumed`, con acción y vencimiento;
- acciones, aprobaciones, timeouts y elementos `unknown`;
- timeline operacional, técnico y conversacional;
- profundidad por carril, antigüedad del trabajo pendiente, retraso de procesamiento y capacidad disponible;
- estado `live`, `stale`, `degraded` u `offline` de cada integración;
- controles de aprobación, rechazo, directiva, pausa, stop externo y abort.

El dashboard muestra cada directiva como `active`, `rejected`, `expired` o `superseded`, su scope, razón, vencimiento, conflictos y las revisiones del Plan que la aplicaron.

La carga inicial obtiene un snapshot completo; después aplica Realtime. Si se pierde Realtime, usa polling incremental por cursor cada cinco segundos. El orden visual usa secuencia, versión y timestamps persistidos, no el orden de llegada al navegador.

La interfaz ofrece alto contraste, navegación por teclado y estados que no dependen solo del color.

## 13. Integraciones y fallbacks

El núcleo debe funcionar con las capacidades disponibles hoy: Web Voice, Webhooks, AI, Conditions, Chatbot, nodos de Email, Realtime y Supabase. La ausencia actual de números, SIP, KB o MCP no puede bloquear la demo.

| Necesidad | Primera opción | Fallback |
| --- | --- | --- |
| Intake humano | PSTN si se configura | Web Voice → Chatbot → webhook |
| Geolocalización | Locate/Maps | catálogo local de zonas |
| Respuesta de campo | WhatsApp | SMS → outbound voice → enlace web |
| Centro de mando | Teams **o** Slack | dashboard `/ops` |
| Email real | email configurado | registro/dashboard u otro canal |
| Playbook | Knowledge Base | contenido versionado del pack |
| Actualización UI | Supabase Realtime | polling incremental |
| Detalle técnico de conversación | HappyRobot Realtime | estado persistido resumido |

Solo se activa un canal si sus credenciales y destinatarios están disponibles. Un enlace web debe transportarse por un canal real o mostrarse en `/ops`; mostrarlo por sí solo no cuenta como interacción externa.

Twin, Redis, Google Sheets, MCP, Capacity, Negotiation y CXone no forman parte del núcleo. Tampoco se usan Schedule/Sleep de HappyRobot como reloj crítico. Teams y Slack no se activan simultáneamente.

## 14. Prompt assembler generalista

Cada workflow tiene un prompt base estable. Un Context Builder añade únicamente lo que necesita:

- Intake: extracción, seguridad, terminología, localización y esquema Signal.
- Command: objetivos, policies, action catalog, recursos, grafos y snapshot observable.
- Coordination: misión, entidad, canales, deadlines y contrato de respuesta.

El Context Builder es stateless entre runs: reconstruye el contexto desde la snapshot del run para cada dispatch y no reutiliza memoria conversacional, variables mutables globales, fragmentos de Knowledge Base ni resultados de otro pack. Todo prompt lleva `run_id`, `pack_id`, `pack_version` y `pack_digest`.

Se registran `prompt_template_version`, identidad y digest del pack, `state_version` y fragmentos de playbook usados. `hidden-truth.json` nunca entra en prompts ni contextos de agentes.

## 15. Scenario Packs

Un pack es una unidad declarativa, versionada, validable e inmutable durante el run:

```text
manifest.json
zones.json
impact-edges.json
mobility-edges.json
dependency-edges.json
entities.json
resources.json
action-catalog.json
objectives.json
policies.json
timeline.json
hidden-truth.json
evaluation-rules.json
playbook/
```

El manifest declara `pack_id`, `pack_version`, `scenario_schema_version`, `minimum_engine_version`, idioma, duración, primitivas requeridas e integraciones requeridas/opcionales.

Las únicas primitivas ejecutables por el motor son:

- `allocate_resource`
- `release_resource`
- `update_entity`
- `update_edge`
- `contact_entity`
- `broadcast_message`
- `create_task`
- `schedule_review`
- `request_approval`
- `record_outcome`

`action-catalog.json` traduce verbos del escenario a estas primitivas mediante parámetros cerrados. No admite scripts arbitrarios.

`policies.json` declara por categoría de acción si admite evidencia provisional, cuántos clusters `confirmed_independent` y qué clases de origen constituyen corroboración suficiente, qué riesgo exige aprobación humana y cómo se actúa al retractarse o reagruparse una evidencia. Cada regla se clasifica como `hard_constraint` u `objective`: las restricciones duras participan en el nivel 2 de precedencia y los objetivos en el nivel 4. Estas reglas son deterministas y no sustituyen el razonamiento cualitativo de prioridad.

El preflight valida JSON Schema, referencias internas, IDs, grafos, capacidades, recursos, correspondencia entre `resource_mode` y disposición de cada acción, clasificación y completitud de las policies de evidencia, corroboración y retractación, timeline, condiciones terminales, integraciones y compatibilidad con el engine. Si falta una integración requerida, el pack es incompatible. Si falta una opcional, se registra el fallback antes de empezar.

El motor ejecuta exactamente un pack por run. Un pack puede contener varios hazards y cascadas mediante los grafos de impacto y dependencia, pero no puede importar ni combinar otro pack en runtime.

Cada run persiste el digest del pack y una snapshot inmutable. El motor nunca migra silenciosamente un pack incompatible.

El Action Catalog, las policies, los recursos y los grafos se resuelven exclusivamente desde esa snapshot. El Gateway rechaza cualquier acción, entidad, recurso o edge que no pertenezca al pack del run, aunque el identificador haya existido en una ejecución anterior.

## 16. Scenario Packs de aceptación

### 16.1 DANA/inundación — completo

Escenario históricamente inspirado en la DANA de Valencia 2024, con todos los hechos operativos, contactos y decisiones marcados como ficticios.

- **A:** dos personas atrapadas en una planta baja de Paiporta; señal inmediata y corroborada.
- **B:** centro de salud de Catarroja que debe preparar evacuación; más personas, pero una ventana mayor.
- **C:** supuesto colapso de un puente; evidencia débil y ruidosa.
- **Recurso escaso:** un equipo de rescate acuático.
- **Decisión inicial esperada:** asignar el equipo a A, preparar B en paralelo y verificar C.
- **Cambio dinámico:** se bloquea la ruta prevista hacia A y obliga a replanificar.

La demo dura 8–10 minutos comprimidos y muestra entrada, ruido, priorización, contacto real controlado, aprobación, bloqueo, replanificación y postmortem.

El E2E de DANA solo pasa si el equipo se reserva primero para A, B recibe preparación sin doble asignación, C no provoca un despliegue irreversible basado únicamente en ruido y la ruta cerrada deja de utilizarse tras la replanificación. Para C, un rumor original y veinte reenvíos o reformulaciones con IDs distintos deben mostrarse como 21 Signals pero un único cluster de procedencia; solo una observación realmente independiente puede aumentar la corroboración.

### 16.2 Cinco packs mínimos

Cada pack mínimo contiene 2–3 zonas, 3–5 entidades, un recurso escaso, 3–5 señales con al menos una ruidosa, un cambio dinámico, 2–3 primitivas y una regla principal de evaluación.

| Pack | Mundo y recurso | Señales y ruido | Cambio y primitivas | Regla principal |
| --- | --- | --- | --- | --- |
| Incendio forestal | Pinar Norte, Urbanización Este y Corredor Sur; una brigada | Avistamiento, lectura de viento, llamada local y vídeo antiguo | Cambio de viento; `allocate_resource`, `broadcast_message`, `release_resource` | Tras evidencia creíble del viento, proteger la nueva zona expuesta sin usar el vídeo antiguo como causa única |
| Apagón regional | Distrito Hospitalario, Subestación Central y Barrio Sur; un generador móvil | Telemetría, autonomía hospitalaria, petición residencial y rumor de apagón nacional | Se retrasa la recuperación; `allocate_resource`, `contact_entity`, `schedule_review` | Mantener prioridad hospitalaria mientras haya riesgo crítico |
| Fuga química | Planta Industrial, Sector Este y Barrio Oeste; un equipo HAZMAT | Sensor, aviso de planta, reporte escolar y rumor con viento erróneo | Cambia el viento; `allocate_resource`, `contact_entity`, `broadcast_message` | Actualizar protección y avisos según la exposición vigente, no según el rumor |
| Terremoto | Casco Antiguo, Corredor Hospitalario y Depósito Norte; un equipo de rescate pesado | Atrapamiento corroborado, alarma estructural, estado de carretera y rumor de réplica | Una réplica real bloquea la ruta; `allocate_resource`, `create_task`, `update_edge` | Mantener la prioridad del atrapamiento y crear una alternativa sin reutilizar la ruta cerrada |
| Humanitaria/logística | Almacén Central, Campamento Este y Campamento Oeste; un vehículo de cadena de frío | Insulina urgente, petición de alimentos, telemetría y rumor antiguo de checkpoint | Se degrada la ruta a Este; `allocate_resource`, `contact_entity`, `update_edge` | Preservar prioridad médica y adaptar la ruta sin cancelar por el rumor antiguo |

Estos packs no son variaciones nominales de DANA: ejercitan propagación, dependencia crítica, exposición, movilidad y prioridad logística diferentes.

## 17. Fallos y degradación

| Situación | Comportamiento |
| --- | --- |
| Comando duplicado | Devuelve el resultado original sin nueva mutación |
| Conflicto de versión | Relee y replantea; nunca sobrescribe |
| Fallo antes de commit | No hay cambio |
| Fallo después de commit | Repetir el mismo `command_id` recupera el resultado |
| Supabase no disponible | Pausa estímulos y nuevos efectos externos |
| Realtime no disponible | Dashboard pasa a polling y marca datos stale |
| Plan obsoleto | Rechaza despacho y activa Command |
| Evidencia retractada | Bloquea dependientes, revalida la evidencia restante y cancela solo lo insuficiente |
| Directiva incompatible | Se rechaza con invariantes o directivas en conflicto; no cambia el dominio |
| Integración ausente | Usa fallback declarado antes de crear intento |
| Fallo conocido sin efecto, bajo riesgo | Reintento limitado |
| Efecto externo incierto | `unknown`, sin reintento ciego |
| Reserva `held` expirada | `expired`, libera capacidad y activa Command |
| Reserva `quarantined` | Bloqueada hasta que una persona confirme uso o liberación |
| Callback después del cierre | Se guarda en `late_external_events`; no muta ni reactiva el run |
| IA no disponible | No crea nuevas acciones de impacto; deriva a revisión |
| Commander interrumpido | Lease expira, conserva `dirty` y se reanuda desde Supabase |
| Tormenta de señales | Persiste entradas, agrupa trabajo compatible y reserva capacidad para `control` y `outcome` |

El sistema promete idempotencia del estado interno, no `exactly-once` en sistemas externos.

## 18. Pruebas y evaluación

### 18.1 Dos capas E2E

**Capa HappyRobot**

- `whole_run` sobre `crisis-command` para los seis packs;
- `agent_isolated` para extracción/revisiones de Intake;
- `agent_isolated` para aceptación, rechazo, timeout y `unknown` de Coordination.

Estas pruebas evalúan prompts, razonamiento, herramientas y comportamiento dentro de un workflow. No certifican los saltos entre workflows.

**Capa sistema**

El Scenario Controller ejecuta un E2E por pack atravesando:

```text
entrada → Intake → Gateway/Supabase → Event Router → Command
        → aprobación → Coordination → outcome → replanificación
```

Esta capa es la prueba autoritativa de la arquitectura distribuida.

Además se ejecuta una prueba de aislamiento secuencial:

```text
DANA completa → cerrar run → incendio forestal → cerrar run
```

El segundo run debe cargar una snapshot nueva y no puede contener IDs, recursos, acciones, fragmentos de playbook ni terminología operativa exclusiva de DANA. La prueba cubre dos rechazos: una referencia al digest DANA dentro del run de incendio devuelve `pack_context_mismatch`; una acción DANA enviada con la identidad correcta del pack de incendio devuelve `action_not_in_active_pack`.

### 18.2 Invariantes de prueba

Todos los E2E comprueban:

- ausencia de doble asignación o disponibilidad negativa;
- ninguna reserva `held` permanece después de su expiración y ninguna `quarantined` se libera automáticamente;
- un recurso reutilizable se libera y una unidad consumible se descuenta exactamente una vez tras su Outcome;
- rechazo de planes y acciones obsoletos;
- ninguna acción de alto impacto sin aprobación;
- una directiva válida afecta al siguiente Plan y una directiva incompatible se rechaza sin mutación parcial;
- ningún reintento ciego tras un efecto incierto;
- ruido insuficiente como única base para una acción irreversible;
- múltiples copias del mismo origen cuentan como un cluster, no como corroboraciones independientes;
- una revisión retractada no sustenta nuevas autorizaciones; las acciones sin evidencia activa suficiente se cancelan antes del despacho;
- rutas cerradas no utilizadas después de su actualización;
- todo incidente activo atendido, verificado o aplazado con razón y `revisit_at`;
- correlación entre evento, plan, acción, intento y outcome;
- ausencia de `hidden_truth` en prompts o vistas activas;
- ningún efecto externo posee `dispatch_authorized_at` posterior a `closed_at` ni `authorized_state_version` posterior a `terminal_state_version`;
- ningún callback tardío cambia `terminal_state_version`, la puntuación o el estado operativo;
- paso por los tres workflows en cada pack.

`hidden-truth.json` incluye un canary que las pruebas buscan en todos los contextos visibles antes del postmortem.

### 18.3 E2E de saturación y prioridad

Una prueba adicional inyecta 500 entradas estructuradas, incluidas entregas idempotentes repetidas y numerosos ecos del mismo origen. Mientras `signal_batch` mantiene trabajo pendiente, introduce una aprobación, un cierre de ruta y un Outcome crítico.

La prueba exige que:

- todas las entradas únicas sean recuperables y las repeticiones idempotentes reutilicen su recibo;
- los ecos permanezcan trazables como Signals individuales cuando corresponda, pero no se conviertan en corroboraciones independientes;
- `control` y `outcome` se despachen antes que el backlog normal;
- la concurrencia observada nunca exceda la configuración capturada en el run;
- el número de invocaciones de Intake sea menor que el número de entradas gracias al batching y la deduplicación;
- `queue_depth`, antigüedad y retraso reflejen la saturación y el estado pase a `degraded`;
- tras drenar la cola, el Plan incorpore los eventos urgentes y todas sus decisiones conserven evidencia trazable.

### 18.4 Ensayo live

Solo DANA exige ensayo live completo. Usa destinatarios controlados, whitelist, entorno development y mensajes `SIMULACIÓN`. Los otros cinco packs prueban generalidad mediante E2E de sistema sin exigir seis integraciones reales distintas.

### 18.5 Postmortem y aprendizaje

Al completar o abortar:

1. se congela el estado operativo;
2. se revela la verdad oculta al evaluador y a la vista de postmortem;
3. se compara `truth → signals → operational belief → decisions → outcomes`;
4. se ejecutan reglas deterministas del pack;
5. HappyRobot realiza una evaluación cualitativa de decisión, ejecución y supervisión;
6. se generan lecciones candidatas con evidencia y alcance;
7. una persona aprueba, edita o rechaza cada lección.

Ninguna lección modifica automáticamente prompts, policies, playbooks ni reglas de evaluación.

El postmortem se calcula contra `terminal_state_version`. Los eventos de `late_external_events` aparecen en un anexo con su tiempo real de recepción, pero no recalculan silenciosamente reglas, puntuaciones ni lecciones del run cerrado.

## 19. Invariantes normativos

1. Todo registro de dominio pertenece a un `run_id`.
2. Solo el Gateway modifica estado autoritativo.
3. Estado, eventos, outbox, resultado del comando y versión se confirman atómicamente.
4. Un comando duplicado no cambia estado ni versión.
5. Una validación fallida no produce efectos laterales.
6. El reloj de escenario no retrocede ni se deriva del reloj del servidor.
7. La verdad oculta no es visible para workflows, operador o facilitador durante un run activo.
8. Existe como máximo un Commander activo por crisis.
9. Una acción pertenece a una revisión concreta del plan.
10. Una acción siempre conserva evidencia observable y razonamiento.
11. Un recurso no puede estar reservado de forma incompatible por dos acciones.
12. Un efecto simulado se aplica por un outcome confirmado, no por una intención.
13. Los outcomes y eventos son append-only.
14. Solo eventos de la allowlist disparan workflows.
15. Realtime no determina orden ni completitud.
16. Cada ejecución externa usa un `dispatch_id` estable.
17. `unknown` nunca se convierte automáticamente en éxito o fallo.
18. Una arista solo puede consultarse dentro de su capa de grafo.
19. Ningún prompt, comando o acción puede mezclar identidades o contenido de dos packs.
20. Toda unidad no disponible está respaldada por una reserva activa y toda reserva activa pertenece a una Action.
21. Una reserva `quarantined` solo puede pasar a `committed`, `released` o `consumed` mediante reconciliación humana registrada.
22. Un run terminal nunca cambia su `terminal_state_version` y ningún evento tardío crea trabajo operativo.
23. Todo efecto externo está respaldado por una autorización persistida mientras el run estaba activo.
24. Ninguna decisión nueva puede usar una revisión `superseded` o `retracted` como evidencia activa.
25. Retractar evidencia no elimina ni reescribe decisiones o comunicaciones históricas.
26. La corroboración para acciones de alto impacto se calcula por clusters `confirmed_independent`, nunca por cantidad bruta de Signals.
27. Una HumanDirective nunca puede violar un invariante transaccional ni modificar directamente el estado factual.
28. Toda directiva activa aparece de forma explícita en el Plan, junto con su aplicación o la condición de mayor precedencia que impide cumplirla.

## 20. Evolución del repositorio actual

Los cinco schemas actuales son prototipos v1 y contienen decisiones específicas de DANA: `downstream_of`, elevación, verbos concretos, un único canal, estados incompletos y escrituras directas desde HappyRobot.

La implementación debe:

- conservarlos bajo namespace/directorio `v1` o sustituirlos de forma atómica por contratos explícitamente v2;
- impedir la aceptación runtime de contratos sin versión;
- mover propagación, verbos y policies específicos al Scenario Pack;
- separar recursos de entidades y evitar contadores duplicados;
- crear schemas para Incident, Plan, Outcome, Command, Approval y eventos;
- actualizar README y ejemplos para reflejar los tres workflows y el Gateway;
- mantener la decisión existente de usar REST/Webhooks de HappyRobot y no MCP.

Los ejemplos anteriores de incendio o logística son material histórico, no contratos del nuevo sistema.

## 21. Decisiones descartadas

- Un workflow por fuente: fragmenta el plan global y duplica lógica.
- Escrituras directas a Supabase desde cada componente: crean carreras y ownership ambiguo.
- Event sourcing puro: innecesario para la demo; se mantienen estado materializado y eventos append-only.
- Solo E2E de HappyRobot: no prueba Supabase, Router ni los saltos entre workflows.
- Solo E2E externo: pierde la evaluación específica de prompts y nodos.
- Un pack rígido de DANA: no demuestra generalidad.
- Scripts arbitrarios en packs: rompen auditabilidad y aislamiento.
- Reintento ciego de efectos externos: puede duplicar comunicaciones o acciones.
- Twin, Redis, Sheets o MCP como dependencia central: no están disponibles ni son necesarios.

## 22. Condición de diseño terminado

El diseño se considera implementado cuando:

1. los tres workflows respetan sus fronteras;
2. todas las mutaciones pasan por el State Gateway;
3. DANA completa el ensayo live de 8–10 minutos;
4. los seis packs completan el E2E de sistema sin violar invariantes;
5. HappyRobot ejecuta las pruebas nativas definidas;
6. el dashboard permite observar, aprobar, intervenir y revisar el postmortem;
7. la prueba secuencial DANA → incendio demuestra aislamiento entre packs;
8. los E2E prueban expiración, liberación, consumo y cuarentena de reservas sin sobreasignación;
9. un callback posterior al cierre queda en el anexo sin alterar estado ni evaluación;
10. un E2E provisional → retractación reevalúa dependientes, invalida los insuficientes, libera la reserva segura y conserva la historia;
11. el E2E de rumor replicado demuestra que 21 Signals no idénticas de un mismo origen cuentan como un solo cluster;
12. un E2E de intervención aplica una directiva válida, rechaza otra que usa una ruta cerrada y replantea al expirar;
13. el E2E de saturación conserva todas las entradas únicas, prioriza control y outcomes y respeta los límites de concurrencia;
14. ninguna dependencia opcional es necesaria para que funcione el camino base.
