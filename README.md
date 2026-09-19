# Valte v2 — HackSpain 2026 · reto HappyRobot

Sistema agéntico de gestión de crisis. Tres piezas:

| Pieza | Qué es | Dónde |
|---|---|---|
| **Backend** (`backend/`) | El kernel: estado del mundo, validación y ejecución de acciones, contactos reales, API + SSE. Habla con 12 workflows `PedroD-*` de HappyRobot (uno de ellos, `PedroD-proactive`, hace una ronda cada 45 s sin que nada lo despierte: avisa, abre albergues, mueve y repone recursos). | http://localhost:8010 (`/docs`) |
| **Dashboard** (`frontend/`) | Las pantallas del diseño (`Valte · Pantallas.html`) conectadas a la API en vivo. Lo sirve el propio backend. | http://localhost:8010/app/ |
| **Mundo exterior** (`simulator/`) | App ligera con un botón **Start**: empieza a enviar llamadas al 112, redes, medios y sensores, y permite provocar imprevistos. | http://localhost:8030 |

## Arrancar

```bash
backend/scripts/dev_server.sh 8010      # kernel + dashboard   (el 8000 lo ocupa un uvicorn antiguo del v1)
backend/scripts/tunnel.sh 8010          # en su PROPIA línea de comandos: URL pública para los callbacks de HappyRobot
simulator/run.sh 8030                   # mundo exterior
```

1. Abre **http://localhost:8030** y pulsa **Start** (crea la crisis «Riada en Paiporta» y empieza a enviar datos), o declara la
   crisis desde el dashboard («Iniciar catástrofe») y en Mundo exterior elige *Alimentar · …* antes de pulsar Start.
2. Abre **http://localhost:8010/app/**, entra en la crisis y mira cómo se mueve: señales (con el ruido tachado), decisiones del
   agente con su razonamiento y evidencia, plan, cuentas atrás por zona, aprobaciones con temporizador, contactos.
   En el panel de Coordinación: **Últimos cambios** (qué ha cambiado en los últimos minutos, en una línea cada cosa) y
   «Ver plan, reflejos y lo aprendido →» (objetivos por orden, incidentes P0–P3, por qué se tiró cada plan anterior, reflejos
   armados por el agente y lecciones de ejecuciones pasadas). Desde una zona, «Acciones/Señales de la zona» abre la lista filtrada.
   Desde cualquier panel de rol (Coordinación, Autoridad o Respuesta), **⚑ Reportar incidencia**: solo un nombre («se hunde el
   puente de la CV-36 en Paiporta») y un tipo; la zona, el recurso y las cantidades los saca el sistema del nombre. Entra como
   aviso fiable y cambia el mundo en el acto (acceso más lento, recursos descontados, unidades despachadas, plan invalidado).
   En **Zonas**, dos vistas: **Mapa** (las zonas sobre el territorio, coloreadas por severidad, con su cuenta atrás, los avisos
   con ubicación de calle y «acceso cortado») y **Tiempos de llegada** (el grafo de propagación del diseño). Las zonas del pack
   traen coordenadas; las que se escriben en el wizard se localizan solas por nombre (OpenStreetMap).
3. Interviene: aprueba o rechaza, actúa como Alcaldía desde su panel, atiende la llamada entrante del agente, o provoca un
   «¿y si…?» desde Mundo exterior (puente cortado, entidad que no contesta, fuente que enmudece…).

Cada crisis recibe **su propio guion**: «Riada en Paiporta» usa el escrito a mano; cualquier otra (incendio, apagón, fallo de
infraestructura, víctimas múltiples… sobre las zonas que dibujes en el wizard) recibe uno generado a partir de su grafo de zonas
y sus retardos (`backend/valte/sim/generator.py`, `GET /crises/{id}/timeline`), con ruido, rumores, sensores que enmudecen, una
entidad que deja de contestar, una carretera cortada y pérdida de recursos.

Utilidades: `backend/scripts/tunnel_watch.sh 8010` (reabre el túnel cuando caduca), `backend/scripts/delete_crisis.py <id|código>`
(borra un ensayo y lo que aprendió), `backend/scripts/reset_db.py` (limpia el mundo, conserva los workflows).

Cada decisión del coordinador cuesta ~1 crédito de HappyRobot: **pausa o cierra** la crisis al terminar.
Para probar sin gastar: `VALTE_BRAIN=local VALTE_OUTREACH_MODE=dry backend/scripts/dev_server.sh 8011` y
`VALTE_BACKEND=http://localhost:8011 simulator/run.sh 8031`.

Pendiente de configurar: `DEMO_EMAIL_TO` en `.env` (buzón al que se reescriben todos los emails reales; vacío = los emails
quedan marcados como *simulado* y no se envía nada).

## Dashboard: cómo está hecho

No es una reimplementación: son las plantillas del propio export de diseño (runtime `dc-runtime` + componentes `Valte.*`),
con los datos mock sustituidos por la API.

```bash
python3 frontend/extract_design.py   # una vez: saca del export el runtime, los componentes, fuentes, CSS y el marcado original (design/)
python3 frontend/build.py            # src/ → dist/ (lo que sirve el backend en /app/)
```

- `frontend/src/<Pantalla>.body.html` — marcado del diseño con sus listas fijas convertidas en bucles (`sc-for`/`sc-if`).
- `frontend/src/<Pantalla>.logic.js` — de dónde salen los datos (API) y qué hace cada botón.
- `frontend/src/valte-live.js` — cliente de la API, stream de eventos (recarga con debounce al cambiar algo), cabecera común
  (reloj, severidad, KPIs, selector de rol, **aviso de llamada entrante**), aprobar/rechazar y voz con `livekit-client`.
- El lienzo del diseño es fijo (1440×900) y se escala a la ventana. `?static=1` renderiza sin stream (capturas).
- Los recursos son de cada entidad: las pantallas piden el inventario «como» la entidad del panel de rol del que vienes
  (CECOPI lo ve todo; Bomberos solo lo suyo; una Guardia Civil no ve cuántos bomberos quedan). `?as=<entidad>&asrole=responder|authority` abre cualquier pantalla como esa entidad.
- La crisis activa viaja en `?c=<id>` y se recuerda en `localStorage`; en un panel de rol, pulsar el segmento activo
  cambia de entidad (p. ej. de Alcaldía de Paiporta a Ayuntamiento de Chiva).

Guion de la demo, con qué decir en cada minuto y qué hacer si algo falla: [docs/DEMO.md](docs/DEMO.md).

Detalle del backend, contratos y workflows: [backend/README.md](backend/README.md).
