# frontend

Dashboard de Valte (Vite + React + TS).

## Run (dev)

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

Necesita el backend en marcha (`../backend`, puerto 8000). La URL sale
de `VITE_API_BASE_URL` en el `.env` de la raíz.

## Qué hay

Una sola pantalla: el botón grande **CREAR CRISIS**. Al pulsarlo pide el
micro, abre una llamada web contra el agente de voz `crisis-start` de
HappyRobot (ver `../workflows/crisis-start.md`) y muestra la
transcripción en vivo. El halo del botón sigue tu nivel de micro. Se
vuelve a pulsar para colgar.

Al colgar, manda la transcripción y el `run_id` a `POST /crisis`: el
backend guarda la crisis en Supabase, busca los manuales de gestión en
internet y los guarda también. La UI los lista con su fuente.

El token de LiveKit lo emite el backend (`POST /crisis/voice-token`);
la API key de HappyRobot no llega nunca al navegador.

## Estructura

- `src/App.tsx` — la pantalla.
- `src/useCrisisCall.ts` — el hook que lleva la llamada (token, sala
  LiveKit, micro, transcripciones).
- `src/index.css` — estilos.
