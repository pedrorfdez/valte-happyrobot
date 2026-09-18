# HappyRobot API examples

Estos ejemplos usan la API REST de HappyRobot en la región EU y cargan la
clave desde el `.env` de la raíz del proyecto. Necesitan `curl`, `jq` y una
variable `HAPPYROBOT_KEY` válida.

## Preparación

```bash
export WORKFLOW_ID="<workflow-id>"
export HAPPYROBOT_ENV=development
```

También puedes guardar `WORKFLOW_ID` en `.env`. El entorno por defecto es
`development` para que un ejemplo no dispare accidentalmente un workflow de
producción.

## Recorrido recomendado

```bash
# 1. Descubrir workflows disponibles
./examples/01-list-workflows.sh

# 2. Inspeccionar uno
./examples/02-get-workflow.sh "$WORKFLOW_ID"

# 3. Disparar un incidente de demostración
./examples/03-trigger-crisis-workflow.sh "$WORKFLOW_ID"

# 4. Observar las ejecuciones
./examples/04-list-workflow-runs.sh "$WORKFLOW_ID"
./examples/04-list-workflow-runs.sh "$WORKFLOW_ID" running

# 5. Crear un token limitado para una interfaz de chat o voz
./examples/05-create-chat-token.sh "$WORKFLOW_ID"
./examples/06-create-voice-token.sh "$WORKFLOW_ID"

# 6. Simular el caso DHL de alerta de temperatura
./examples/07-dhl-temperature-alert.sh "$WORKFLOW_ID"
```

El tercer ejemplo acepta `INCIDENT_ID` para correlacionar el evento:

```bash
INCIDENT_ID="fire-zone-a-001" ./examples/03-trigger-crisis-workflow.sh "$WORKFLOW_ID"
```

## Caso de uso: alerta de temperatura en cadena de frío

Este ejemplo adapta el caso público de DHL: un sensor detecta que una
mercancía sensible a la temperatura ha superado el umbral y el workflow recibe
el contexto para llamar al operador, escalar al centro de control y avisar al
responsable de guardia.

Por seguridad, funciona en simulación. Para enviar la alerta al workflow:

```bash
DRY_RUN=false \
TEMPERATURE_C=10.4 \
TEMPERATURE_THRESHOLD_C=8.0 \
SHIPMENT_ID="DHL-INSULIN-001" \
./examples/07-dhl-temperature-alert.sh "$WORKFLOW_ID"
```

Para probar una lectura que no supera el umbral:

```bash
DRY_RUN=false TEMPERATURE_C=6.5 ./examples/07-dhl-temperature-alert.sh "$WORKFLOW_ID"
```

## Decisiones de seguridad

- `HAPPYROBOT_KEY` solo se usa en estos scripts de servidor/locales y nunca se
  imprime.
- Los tokens de chat y voz tienen una duración corta y deben generarse desde
  un backend. El navegador recibe únicamente el token limitado.
- El ejemplo de disparo usa `development` por defecto; cambia
  `HAPPYROBOT_ENV` de forma explícita cuando quieras probar otro entorno.

## Fuentes oficiales consultadas

Los patrones de token y ciclo de vida están adaptados de los ejemplos públicos
de HappyRobot:

- [chatbot-sdk-example](https://github.com/happyrobot-ai/chatbot-sdk-example)
- [voice-sdk-example](https://github.com/happyrobot-ai/voice-sdk-example)
- [happyrobot-python](https://github.com/happyrobot-ai/happyrobot-python)

Los endpoints REST se contrastaron con el [OpenAPI público de la plataforma](https://platform.eu.happyrobot.ai/api/v2/docs/json).

El comportamiento del caso se basa en el [caso público de DHL](https://www.happyrobot.ai/customer-story/dhl), no en código interno de DHL o HappyRobot, que no está publicado.
