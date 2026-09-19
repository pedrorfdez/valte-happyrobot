# Diseño del README de arranque local

**Estado:** pendiente de revisión del usuario  
**Fecha:** 2026-09-19  
**Tipo de documento:** guía práctica (`how-to`)  
**Audiencia principal:** equipo técnico de la demo

## 1. Objetivo

Convertir el `README.md` raíz en el punto de entrada único para preparar y lanzar el proyecto localmente, desde un clon limpio hasta la ejecución secuencial DANA → incendio.

La guía también conservará una sección breve para el estado actual del repositorio, porque hoy solo están implementados los contratos v2 y su validador. Los comandos del sistema completo se documentarán como recorrido objetivo y quedarán marcados como disponibles únicamente cuando se ejecuten los seis planes de implementación.

## 2. Principios

- Priorizar el arranque local; Azure queda como despliegue opcional.
- Presentar un único orden feliz, paso a paso.
- Incluir comandos copiables y resultados esperados.
- No inventar scripts, endpoints, variables o archivos distintos de los planes aprobados.
- Diferenciar visualmente `Disponible ahora` de `Disponible tras implementar los seis frentes`.
- Mantener `SIMULACIÓN` y `dry-run` como valores seguros por defecto.
- No incluir secretos, teléfonos ni direcciones reales.
- Explicar cómo parar y reiniciar la demo sin borrar datos ajenos.
- Enlazar los documentos especializados en lugar de duplicar su contenido completo.

## 3. Estructura aprobada

### 3.1 Resumen y estado actual

Abrirá con una explicación de una frase del sistema y una tabla pequeña:

| Capacidad | Estado |
| --- | --- |
| Contratos v2 y ejemplos DANA/incendio | disponible |
| Supabase/Gateway | planificado |
| Scenario Controller | planificado |
| HappyRobot | planificado |
| Dashboard SWA | planificado |
| Interacción real y E2E | planificado |

Esto impide que alguien intente lanzar archivos que todavía no existen.

### 3.2 Quick start disponible hoy

El recorrido actual será:

```bash
npm ci
npm run contracts:check
```

La guía mostrará las dos líneas `PASS` esperadas.

### 3.3 Prerrequisitos para el sistema completo

Lista breve y verificable:

- Node.js 24 y npm;
- `psql` y acceso a un proyecto Supabase;
- Azure Functions Core Tools/SWA CLI para el Gateway local cuando esté implementado;
- `curl` y `jq`;
- acceso al entorno `development` de HappyRobot;
- claves locales copiadas desde `.env.example` a `.env`.

Cada herramienta tendrá un comando corto para comprobar su versión. La guía no instalará herramientas automáticamente.

### 3.4 Configuración de variables

Explicará copiar `.env.example` a `.env` y completar:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
DATABASE_URL
GATEWAY_URL
HAPPYROBOT_KEY
HAPPYROBOT_BASE_URL
HAPPYROBOT_ENV
HAPPYROBOT_INTAKE_WORKFLOW_ID
HAPPYROBOT_COMMAND_WORKFLOW_ID
HAPPYROBOT_COORDINATION_WORKFLOW_ID
DANA_RUN_ID
WILDFIRE_RUN_ID
DEMO_INTERACTION_MODE
```

Indicará qué variables son públicas y cuáles permanecen únicamente en servidor/local, sin convertir el README en una guía de seguridad productiva.

### 3.5 Arranque local completo

El orden será obligatorio:

1. Instalar dependencias y validar contratos.
2. Aplicar migración y seed de Supabase.
3. Iniciar las Functions del Gateway.
4. Configurar/publicar los tres workflows HappyRobot en `development`.
5. Levantar el dashboard estático.
6. Ejecutar preflight.
7. Ejecutar el E2E secuencial DANA → incendio.

Cada paso incluirá:

- terminal recomendada;
- comando;
- salida o endpoint esperado;
- condición para continuar;
- enlace al plan detallado correspondiente.

La guía advertirá que el Scenario Controller termina de emitir el timeline antes de que el E2E drene el Event Router. Esto evita carreras sobre `state_version`.

### 3.6 Interacción real controlada

`DEMO_INTERACTION_MODE=dry-run` será el valor predeterminado. Web Voice o email solo se activarán después del checklist de `docs/demo-contacts.md`, con destinatario consentido y mensaje `SIMULACIÓN`.

El README no reproducirá credenciales ni datos de contacto.

### 3.7 Despliegue opcional en Azure

Será una sección corta que indique:

- `app/` como contenido estático;
- `api/` como managed Functions;
- `staticwebapp.config.json` como configuración;
- variables de servidor configuradas en Azure, nunca incrustadas en el frontend;
- validación del endpoint `/api/snapshot` después del despliegue.

No se documentará infraestructura como código ni CI/CD porque están fuera de este incremento.

### 3.8 Parada, reset y troubleshooting

Incluirá:

- cómo detener procesos locales con `Ctrl-C`;
- cómo reaplicar únicamente `supabase/seed.sql` para restaurar los dos runs de demo;
- síntomas y correcciones para variables ausentes, `version_conflict`, workflow no encontrado, Realtime degradado y run no limpio;
- prohibición de ampliar los `DELETE` del seed más allá de `run-dana-demo` y `run-wildfire-demo`.

## 4. Alcance excluido

- Tutorial de Supabase, Azure o HappyRobot desde cero.
- Seguridad o autenticación productiva.
- CI/CD y aprovisionamiento de infraestructura.
- Los otros cuatro Scenario Packs.
- Explicación completa de la arquitectura y contratos.
- Comandos alternativos para Windows; la guía asumirá macOS/Linux y shell compatible con `zsh`/`bash`.

## 5. Criterios de aceptación

El README estará listo cuando:

1. un miembro técnico pueda identificar en menos de un minuto qué funciona hoy;
2. el quick start actual ejecute `npm run contracts:check` correctamente;
3. el recorrido completo use exclusivamente nombres y comandos presentes en los planes aprobados;
4. DANA e incendio utilicen los mismos contratos y workflows;
5. ningún secreto o contacto real aparezca en el documento;
6. no haya marcadores pendientes ni instrucciones ambiguas;
7. todos los enlaces locales apunten a archivos existentes;
8. el documento distinga claramente preparación, arranque, verificación, parada y reset.
