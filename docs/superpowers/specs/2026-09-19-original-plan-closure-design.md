# Diseño de cierre del plan general original

**Fecha:** 2026-09-19

## Objetivo

Cerrar de forma reproducible el plan maestro de la demo de crisis DANA → incendio forestal, preservando el trabajo actual, corrigiendo los defectos observados en el dashboard, verificando la integración publicada y dejando el repositorio limpio y documentado.

El cierre demuestra la cadena completa mediante interfaces públicas:

```text
Scenario Controller
  → Intake
  → Command
  → aprobación humana simulada
  → Coordination
  → Outcome
  → replanificación
```

La aceptación conectada se ejecuta en `dry-run`. No se realizan llamadas, emails ni contactos PSTN reales.

## Estado de partida

El núcleo funcional ya existe:

- los contratos v2 de DANA, incendio e interacción pasan su validador;
- los packs DANA e incendio generan nueve comandos deterministas cada uno;
- el Gateway público se sirve mediante Supabase Edge Functions;
- los tres workflows de HappyRobot están publicados y son accesibles en `development`;
- el dashboard local carga snapshots y envía comandos al Gateway;
- existe un runner E2E para DANA → incendio.

La entrega no está cerrada porque:

- hay cuatro archivos versionados modificados y dos scripts sin seguimiento;
- la versión más reciente del prompt Command aún debe integrarse y verificarse contra la publicación;
- el dashboard vuelve a renderizar snapshots idénticos y permite operar sobre Actions de planes sustituidos;
- los runs no están ambos limpios para repetir el recorrido conectado;
- el plan maestro conserva referencias obsoletas a Azure como ruta activa;
- no existe una evidencia final obtenida desde un árbol Git limpio.

## Alcance

### Incluido

1. Revisar e integrar los cambios pendientes existentes sin sobrescribirlos.
2. Corregir los dos defectos observados en el dashboard.
3. Verificar que la definición publicada de Command coincide con el prompt integrado o republicarla de forma controlada.
4. Validar la accesibilidad de los tres workflows publicados.
5. Limpiar los dos runs sólo después de una confirmación explícita, porque el reseed elimina su estado observable actual.
6. Ejecutar el recorrido conectado DANA → incendio en `dry-run`.
7. Repetir la aceptación manual del dashboard sobre estado válido.
8. Actualizar la documentación para reflejar Supabase Edge como Gateway activo.
9. Ejecutar comprobaciones finales, escaneo de secretos y cierre Git.

### Excluido

- llamadas, emails, Web Voice o PSTN reales;
- automatizar Scenario Controller y Event Router dentro de `make up`;
- añadir cuatro packs adicionales;
- reservas avanzadas;
- operaciones completas de retractación, merge o split;
- nuevas colas, backpressure o infraestructura;
- comparación postmortem con la verdad oculta.

La interacción externa queda documentada como implementada contractualmente pero no ejercitada por seguridad. No bloquea este cierre.

## Estrategia de cierre

El trabajo se ejecuta en cinco puertas secuenciales. Una puerta no comienza hasta que la anterior deja evidencia verde.

### Puerta 1 — Preservación e integración local

Se revisan individualmente los cambios actuales:

- `api/event-router/index.mjs`;
- `docs/demo-runbook.md`;
- `happyrobot/crisis-command/commander.prompt.md`;
- `scripts/e2e-demo.mjs`;
- `scripts/check-workflows.sh`;
- `scripts/reseed-runs.sh`.

Cada cambio debe corresponder a un requisito del plan original. Los scripts nuevos deben tener permisos ejecutables, mensajes de error claros y no imprimir claves. La integración se valida con comprobaciones estáticas antes de cualquier mutación remota.

### Puerta 2 — Dashboard correcto y estable

El dashboard conserva todas las Actions como historial observable, pero sólo habilita Aprobar/Rechazar cuando se cumplen simultáneamente estas condiciones:

- la Action está en `snapshot.plan.action_ids`;
- `action.plan_id` coincide con el Plan activo;
- su estado es `pending_approval`;
- su política es `human_required`.

Una Action histórica permanece visible y recibe una indicación de Plan sustituido, pero no presenta controles operativos.

El refresco sigue aceptando snapshots de la misma `state_version`, porque el estado del outbox puede cambiar sin incrementar esa versión. Sin embargo, sólo llama a `render()` cuando el contenido observable del snapshot cambia. El estado de salud y la hora de última sincronización sí se actualizan en cada respuesta válida.

Estas reglas evitan tanto la falsa sensación de bucle como los comandos contra Actions que ya no pertenecen al Plan activo.

### Puerta 3 — Integración publicada

Los IDs configurados de Intake, Command y Coordination se consultan mediante la API de HappyRobot. La comprobación valida accesibilidad sin mostrar tokens.

El prompt Command integrado debe producir al menos una Action `contact_entity` del Plan activo con:

- `status: "pending_approval"`;
- `approval_policy: "human_required"`;
- `params.mission` no vacío y marcado como simulación;
- `params.requested_response` igual a `accept_or_reject` o `acknowledge`.

Si la publicación no contiene el prompt integrado, la ejecución se detiene. La republicación es un paso explícito y auditable; nunca se asume que un archivo local actualizó automáticamente el workflow remoto.

### Puerta 4 — E2E conectado seguro

Antes del reseed se muestra el estado actual de ambos runs y se solicita confirmación explícita. Tras confirmarla, DANA e incendio deben quedar en `ready`, `state_version: 0` y sin objetos de dominio previos.

El runner ejecuta primero DANA y después incendio. Para cada pack:

1. el Controller termina el timeline completo;
2. el Router reclama como máximo un trabajo;
3. se espera progreso observable antes de reclamar el siguiente;
4. se selecciona una Action aprobable del Plan activo;
5. se comprueba la idempotencia de la aprobación;
6. Coordination registra un Outcome en `dry-run`;
7. Command produce una replanificación material;
8. el operador aborta explícitamente el run.

El recorrido de incendio sólo comienza cuando DANA está terminal. La aceptación exige aislamiento de IDs, digest y vocabulario específico entre packs.

Si un dispatch no produce progreso, el runner se detiene y conserva artifacts. No reintenta a ciegas un efecto incierto.

### Puerta 5 — Entrega reproducible

La documentación final presenta Supabase Edge como Gateway público y `make up` como servidor del dashboard, sin afirmar que `make up` ejecuta la simulación.

La entrega final exige:

- validadores y smoke checks verdes;
- artifacts E2E redactados;
- ningún secreto, contacto real ni cabecera Authorization en cambios o artifacts;
- diff sin errores de whitespace;
- commits enfocados y trazables;
- `git status --short` vacío.

## Componentes afectados

| Componente | Responsabilidad del cierre |
| --- | --- |
| `api/event-router/index.mjs` | Validar el límite solicitado manteniendo un único dispatch por llamada. |
| `happyrobot/crisis-command/commander.prompt.md` | Congelar la forma de la Action humana aprobable. |
| `scripts/e2e-demo.mjs` | Ejecutar y verificar la cadena conectada segura. |
| `scripts/check-workflows.sh` | Confirmar los tres workflows publicados sin exponer credenciales. |
| `scripts/reseed-runs.sh` | Recrear runs limpios tras confirmación explícita. |
| `app/app.js` | Evitar renders idénticos y controles sobre Actions históricas. |
| `scripts/test-dashboard-local.sh` y pruebas enfocadas | Cubrir el comportamiento del launcher y las reglas nuevas del dashboard. |
| `README.md` y `docs/demo-runbook.md` | Describir la ruta Supabase y el procedimiento reproducible real. |
| Plan maestro | Registrar desviaciones, evidencia final y gaps deliberados. |

## Manejo de errores y seguridad

- Un árbol de trabajo sucio se revisa; nunca se descarta ni se resetea.
- Un run no limpio bloquea el preflight; no se borra automáticamente.
- El reseed requiere confirmación humana inmediatamente antes de ejecutarse.
- Un `version_conflict` obliga a releer el snapshot; no se sobrescribe estado.
- Un timeout de mutación se trata como resultado incierto hasta reconciliar snapshot y receipt.
- Los efectos externos permanecen en `dry-run` durante toda la aceptación.
- Los scripts no registran claves, tokens ni contactos.
- Un fallo de publicación, workflow o aislamiento detiene la puerta actual y evita los commits de cierre.

## Estrategia de pruebas

### Comprobaciones locales

- validación de contratos;
- sintaxis de JavaScript y JSON;
- dos dry-runs deterministas del Scenario Controller;
- prueba aislada del launcher del dashboard;
- pruebas enfocadas de Actions activas/históricas y render de snapshots iguales;
- `git diff --check`.

### Comprobaciones conectadas

- accesibilidad de los tres workflows;
- preflight de runs limpios;
- E2E DANA → incendio en `dry-run`;
- inspección manual del dashboard durante aprobación, Outcome y replanificación;
- comprobación de aislamiento y artifacts redactados.

### Criterio de aceptación

El plan original queda cerrado cuando una persona puede seguir el runbook desde un checkout limpio, ejecutar la demo conectada sin efectos externos reales, observar la cadena completa en ambos packs y obtener todos los checks esperados sin editar archivos ni recuperar conocimiento de esta sesión.

## Estrategia de commits

Los commits de implementación se mantienen pequeños y reversibles:

1. integrar guardas del Router y scripts operativos;
2. integrar la forma aprobable de Command y el runner E2E;
3. corregir la estabilidad e interacción del dashboard;
4. actualizar runbook, README y plan maestro;
5. registrar únicamente evidencia redactada permitida.

Los archivos actualmente modificados se preservan y se incorporan sólo al commit que corresponde a su responsabilidad.

## Resultado esperado

El repositorio termina con un camino demostrado y documentado para ejecutar DANA y después incendio sobre Supabase Edge y HappyRobot, con aprobación humana simulada, Outcome y replanificación visibles. Los gaps futuros quedan separados del cierre y `make up` conserva su responsabilidad limitada de servir el dashboard.
