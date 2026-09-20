# Valte v2 — HackSpain 2026 · reto HappyRobot

Sistema agéntico de gestión de crisis. El agente **propone**; el kernel **valida**, pide firma para lo grave, **ejecuta** con contactos reales y, si algo falla, **escala y replanifica**. Cada decisión queda con evidencia y porqué.

Tres piezas:

| Pieza | Qué es | Dónde |
|---|---|---|
| **Backend** (`backend/`) | Kernel: estado del mundo, validación y ejecución, contactos reales, API + SSE. 14 workflows `PedroD-*` en HappyRobot. `PedroD-proactive` ronda cada 45 s sin que nadie lo despierte. | http://localhost:8010 (`/docs`) |
| **Dashboard** (`frontend/`) | Pantallas del diseño conectadas a la API en vivo. Lo sirve el propio backend. | http://localhost:8010/app/ |
| **Mundo exterior** (`simulator/`) | Alimenta la crisis con llamadas al 112, redes, medios y sensores. Permite provocar imprevistos. | http://localhost:8030 |

Guion de 5 minutos: [docs/DEMO.md](docs/DEMO.md). Contratos, workflows y API: [backend/README.md](backend/README.md).

## Qué hace

- **Declara la crisis en un cuadro de texto** (escrito o dictado). Valte interpreta escenario, zonas, propagación, recursos y lo que *ya está pasando*; al iniciar, eso entra como primeros avisos del CECOPI: hay severidad, cuentas atrás e incidencias antes de la primera llamada.
- **Agrupa el ruido en incidencias.** Cinco llamadas sobre la misma residencia = una incidencia, con fuentes independientes contadas. Un reenvío de redes no es un testigo. Una sola voz sin corroborar no mueve unidades escasas.
- **Decide sobre el grafo, no sobre el reloj local.** Paiporta puede estar seca y tener 38 minutos de cuenta atrás. El plan estratégico (`crisis-command`) y las acciones tácticas (`coordinator`) son cerebros distintos.
- **Contacta de verdad** (email y llamada web) y escala si no contestan. Aprobaciones humanas con temporizador; voz en el navegador.
- **Aprende en marcha y de una crisis a la siguiente**: quién no contesta, qué se rechazó, qué fuente dio falsas alarmas. Una lección sin evidencia real no se guarda.
- **El terreno corrige el plan.** «Se inunda Sedaví», «nos llegan 200 mantas», «se suma Cruz Roja», «ya hemos cortado el puente»: el mundo cambia en el acto.

## Arrancar

```bash
backend/scripts/dev_server.sh 8010      # kernel + dashboard   (el 8000 lo ocupa un uvicorn antiguo del v1)
backend/scripts/tunnel.sh 8010          # en su PROPIA terminal: URL pública para los callbacks de HappyRobot
simulator/run.sh 8030                   # mundo exterior
```

1. En el dashboard, **Iniciar catástrofe**: escribe o dicta qué pasa y dónde → *Interpretar* (Ctrl+Intro) → revisa lo entendido → *Iniciar catástrofe*.
2. Copia el código de la cabecera (`VLC-7691`, `vlc-7691` o `7691`), ábrelo en http://localhost:8030, elige **Riada** o **Incendio** y pulsa **Start**. Sin código, Start declara una crisis nueva de ese tipo. La riada de Paiporta usa el guion escrito a mano; el resto se genera sobre las zonas de esa crisis.
3. En http://localhost:8010/app/ entra en la crisis: incidencias, decisiones con razonamiento, plan, cuentas atrás, aprobaciones, contactos. Interviene: aprueba, actúa como Alcaldía, atiende la llamada, o provoca un «¿y si…?» desde Mundo exterior.

Cada decisión del coordinador cuesta ~1 crédito de HappyRobot: **pausa o cierra** la crisis al terminar. Sin gastar:

```bash
VALTE_BRAIN=local VALTE_OUTREACH_MODE=dry backend/scripts/dev_server.sh 8011
VALTE_BACKEND=http://localhost:8011 simulator/run.sh 8031
```

Pendiente en `.env`: `DEMO_EMAIL_TO` (buzón al que se reescriben los emails reales; vacío = no se envía nada).

## Durante la crisis

**Coordinación** — Últimos cambios (una línea por cosa que altera el cuadro). Plan, reflejos y lo aprendido (objetivos, incidentes P0–P3, por qué murió cada plan, lecciones de esta crisis y de las anteriores del mismo tipo).

**Zonas** — Mapa (severidad, cuenta atrás, avisos con calle, acceso cortado) y grafo de tiempos de llegada. Las zonas nuevas se geocodifican por nombre (OpenStreetMap).

**Incidencias** — Una o varias señales sobre lo mismo en el mismo sitio. Ruido tachado aparte.

**⚑ Reportar incidencia** (Coordinación, Autoridad, Respuesta) — un nombre y un tipo. También sirve para lo que *ha cambiado*, no solo lo que se ha roto:

| Dices | El kernel |
|---|---|
| «se hunde el puente de la CV-36 en Paiporta» | Acceso más lento, plan invalidado |
| «se inunda Sedaví, 10.500 habitantes» | Zona nueva aguas abajo, ayuntamiento y cuenta atrás |
| «nos llegan 200 mantas y 4 bombas» / «solo quedan 3 bombas» | Suma o corrige inventario |
| «se suma Cruz Roja con 12 voluntarios y 2 embarcaciones» | Alta de entidad con material y capacidades |
| «ya hemos cortado el puente de la CV-36» | Acción tuya ya ejecutada; el agente deja de pedirla |

Un vecino da pistas (fiabilidad baja); una autoridad o unidad da hechos. Lo que hubo que suponer sale en la respuesta.

Cada entidad ve lo suyo en todas las pantallas (CECOPI todo; Bomberos lo suyo; un ayuntamiento su municipio). La población solo tiene Contactos y Reportar.

## Dictado

`POST /stt` transcribe en esta máquina (faster-whisper `small`, grupo `stt` de `backend/pyproject.toml`). El audio no sale de la sala. Primera vez: descarga ~460 MB. `VALTE_STT_MODEL=base` es más rápido y peor con topónimos. Sin el grupo, el endpoint responde 501 y el botón usa el dictado del navegador si lo hay (Chrome, Edge, Safari).

## Utilidades

```bash
backend/scripts/tunnel_watch.sh 8010              # reabre el túnel cuando caduca
backend/scripts/reset_demo.sh                     # borra catástrofes, reinicia kernel + mundo (conserva workflows y lecciones globales)
backend/scripts/delete_crisis.py <id|código>      # borra un ensayo y lo que aprendió
backend/scripts/reset_db.py                       # limpia el mundo, conserva workflows
cd backend && uv run pytest                        # núcleo y API, sin red
```

## Dashboard: cómo está hecho

No es una reimplementación: plantillas del export de diseño (`dc-runtime` + `Valte.*`) con datos vivos.

```bash
python3 frontend/extract_design.py   # una vez: runtime, componentes, fuentes, CSS y marcado original
python3 frontend/build.py            # src/ → dist/ (lo que sirve el backend en /app/)
```

- `frontend/src/<Pantalla>.body.html` — marcado del diseño, listas fijas convertidas en bucles (`sc-for`/`sc-if`).
- `frontend/src/<Pantalla>.logic.js` — de dónde salen los datos y qué hace cada botón.
- `frontend/src/valte-live.js` — cliente API, SSE, cabecera (reloj, severidad, KPIs, rol, llamada entrante), aprobar/rechazar y voz (`livekit-client`).
- Lienzo fijo 1440×900, se escala a la ventana. `?static=1` sin stream (capturas). Crisis activa: `?c=<id>`. Ver como otra entidad: `?as=<entidad>&asrole=responder|authority`.
