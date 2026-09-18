# Workflow: entity (generic decider)

Plantilla aséptica. Representa cualquier entidad del sistema (alcalde,
bomberos, ciudadano, sensor, ...). Todavía no elegimos una concreta:
`{{entity_name}}` y `{{entity_description}}` son placeholders en el
prompt y se sustituyen antes de hacer el `POST /workflows/`.

## Trigger

Webhook HTTP entrante. Payload esperado:

```json
{
  "event_id": "evt_...",
  "from_entity": "citizen_042",
  "kind": "message | sensor | action_result | world_event",
  "content": "...",
  "timestamp": "2026-09-19T14:22:00Z"
}
```

## Decisión

Un solo nodo LLM lee el evento (y, opcionalmente, la memoria) y
devuelve una lista de acciones. **Las acciones NO son excluyentes** —
la entidad puede a la vez actualizar memoria, ejecutar una acción y
comunicarse con otra entidad. `ignore` es el único caso excluyente.

Salida estructurada obligatoria:

```json
{
  "reasoning": "por qué elijo estas acciones",
  "actions": [
    { "type": "update_memory", "payload": { "key": "...", "value": "..." } },
    { "type": "take_action",    "payload": { "action_id": "...", "args": {} } },
    { "type": "communicate",    "target_entity": "firefighters", "payload": { "content": "..." } },
    { "type": "ignore" }
  ]
}
```

## Ejecución de las acciones (todas paralelas)

- `update_memory` → `POST` al backend propio: `/entities/{self_id}/memory`
  (opción A: la memoria vive en nuestro backend, no en HR).
- `take_action` → `POST` al backend: `/actions` (o disparo de un
  workflow HR "action-executor" cuando exista).
- `communicate` → `POST /api/v2/workflows/{target_workflow_id}/runs` en
  HR EU. Cada entidad es un workflow HR distinto, así que "hablar" con
  otra entidad = disparar su workflow con el `payload` como input.
- `ignore` → log-only, sin side effects.

## Identidad

Aséptica por ahora. El prompt del template lleva `{{entity_name}}` y
`{{entity_description}}` como placeholders. Cuando decidamos la primera
entidad concreta, se sustituyen en `entity.create.json` y se hace el
`POST /workflows/`.

## Memoria

Backend propio (opción A). El workflow no persiste estado: en cada
disparo lee/escribe contra el backend. Endpoint y shape de `payload`
por cerrar cuando el backend exista.

## Comunicación entre entidades

Trigger de workflow a workflow (opción A de la pregunta 2). Mantiene HR
como único plano de control y evita construir un router propio en la
primera iteración. El `workflow_id` destino se resuelve por nombre en
un pequeño mapa (por definir, quizá en el propio backend).

## Notas sobre el template

Usamos `chatbot-agent` como template porque:
- Conocemos su schema real (mismo shape que usamos en `emergency-call`
  con `inbound-voice-agent`).
- El canal es texto-in / texto-out estructurado, no voz.
- Si HR ofrece un tipo de workflow "logic/webhook" puro cuando
  veamos la consola, migramos.

## Abiertas

- Nombre exacto del nodo HR que fuerza salida JSON estructurada
  (structured output).
- Cómo HR entrega los inputs del webhook al primer nodo.
- Si existe un workflow-tipo "logic" sin canal conversacional.
