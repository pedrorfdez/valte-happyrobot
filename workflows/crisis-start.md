# Workflow: crisis-start

Admisión de una crisis nueva por voz. Es lo que dispara el botón grande
"CREAR CRISIS" del dashboard.

Creado con `POST /api/v2/workflows/` desde el template
`inbound-voice-agent` (payload exacto en `crisis-start.create.json`).

- Workflow id: `01a0b87b-3bf5-7457-8389-ff168f9845e0`
- Slug: `83q63aene6p7`
- **Versión viva: 3** (`01a0b8b6-515b-7a03-976f-f959fbc51f8e`), env `production`
- Org: `HackSpain - Team 2`

### Versiones

1. `01a0b87b-3c02-...` — la que salió del template. **Inservible:** el
   template deja el agente en inglés (`stt_model: nova-3-onprem-en`,
   `languages: ["en"]`) y voz masculina inglesa, así que el prompt en
   español se hablaba bien pero el español entrante no se transcribía a
   nada: el agente creía que no decías nada.
2. `01a0b8b4-a880-...` — idioma `es` / acento `es-ES` y voz **Ana HR**
   (`31hktsdrgix8`, femenina es-ES).
3. `01a0b8b6-515b-...` — prompt de dictado: abre y calla, no interrumpe,
   y solo repregunta si falta tipo o sitio.

Una versión publicada está **locked**: no se le pueden tocar los nodos.
El ciclo para cambiar algo es `POST /versions/{id}/fork` → `PUT
/versions/{new}/nodes/{node}` → `POST /versions/{new}/publish` con
`{"force": true}`. El idioma y la voz viven en el nodo *Inbound Voice
Agent*, en `configuration.agent.languages` / `language_accents` /
`voices`; el prompt, en el nodo *Prompt*.

## Trigger

Web call desde el navegador. No hay número de teléfono de por medio:

1. El dashboard hace `POST /crisis/voice-token` a nuestro backend.
2. El backend llama a `POST /api/v2/voice/tokens/` con la API key y
   `workflow_id` = este workflow. Devuelve `{ url, token, room_name, run_id }`.
3. El navegador se conecta a esa sala LiveKit con `livekit-client`,
   publica el micro y recibe el audio del agente.

La API key nunca sale del backend.

## Objetivo del agente

Cerrar en menos de 60 s: `crisis_type`, `location`, `started_at`,
`scope`, `people_affected`, `immediate_needs`. Con `crisis_type` +
`location` ya se puede declarar la crisis; el resto son mejoras.

Persona: es-ES, calmada y directiva, una pregunta por turno. Primera
línea: "Valte, centro de crisis. Dime qué está pasando."

## Al colgar

El dashboard hace `POST /crisis` con el `run_id` (y, si las tiene, las
transcripciones que oyó el navegador). El backend guarda la crisis en
Supabase (`crises`), busca en internet los protocolos de gestión que
aplican (Exa) y los guarda en `crisis_manuals`. Tablas en
`backend/sql/002_crises.sql`.

La transcripción **no** se toma del navegador: con el `run_id` el
backend la lee de HR (`/runs/{id}/sessions` → `/sessions/{id}/messages`),
que es el registro que sobrevive. Las transcripciones del navegador son
una comodidad para el operador y se quedan vacías en cuanto el STT se
salta un turno — de hecho así fue como una llamada real acabó sin crear
crisis.

## Speech-to-text

HappyRobot **no expone STT fuera de una sesión de voz**: no hay endpoint
de transcripción en la API v2, y los adjuntos del chat llevan
`artifact_text` (el texto lo aporta el cliente). Así que si queremos que
el STT sea de HR, tiene que ser por este canal de voz. La alternativa
—grabar con MediaRecorder y transcribir con Groq/OpenAI/Deepgram/Whisper
local— evita WebRTC y por tanto el bloqueo de UDP de eduroam, pero saca
el STT de HR.

## Abiertas

- Los campos estructurados (`crisis_type`, `location`, ...) todavía no
  se extraen: la crisis se guarda con la transcripción y esas columnas a
  `null`, y la búsqueda de manuales cae a la transcripción completa.
  Siguiente paso: nodo de salida estructurada en el workflow + webhook a
  `POST /crisis` desde HR, en vez de que lo llame el dashboard.
- Que el propio agente consulte los manuales **durante** la llamada (hoy
  la búsqueda ocurre al colgar, desde el dashboard). HR no tiene nodo de
  búsqueda web, así que sería un tool del workflow apuntando a nuestro
  `POST /crisis/manuals`, o una knowledge base de HR
  (`/knowledge-bases/`) pre-cargada con los protocolos.
