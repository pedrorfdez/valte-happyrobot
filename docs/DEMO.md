# Guion de demo (5 minutos)

La demo cuenta tanto como el sistema. Este guion enseña, en orden, las seis preguntas del reto y los tres bloques de evaluación
con la crisis «Riada en Paiporta» a **20×** (1 minuto de escenario = 3 segundos reales).

## Antes de salir (2 min)

```bash
backend/scripts/dev_server.sh 8010 && simulator/run.sh 8030
nohup backend/scripts/tunnel_watch.sh 8010 > /tmp/valte-tunnel-watch.log 2>&1 &   # reabre el túnel si caduca
curl -s localhost:8010/meta        # 11 workflows, callbacks_authenticated: true, email_configured: true
```

- Dos ventanas: **Mundo exterior** (http://localhost:8030) a la izquierda, **dashboard** (http://localhost:8010/app/) a la derecha.
- Ninguna crisis activa de ensayos anteriores: `backend/scripts/reset_demo.sh` (borra todas y reinicia kernel + mundo)
  o `backend/scripts/delete_crisis.py <código>` si solo quieres quitar una.
- Micrófono permitido en el navegador (para atender la llamada). Si la wifi bloquea WebRTC, usa el móvil como punto de acceso.
- Una crisis de riada ya **cerrada** de un ensayo anterior: así el bloque «Aprendido» no sale vacío.

## El guion

Los sucesos del mundo (aforo que enmudece, puente, residencia…) ocurren en el minuto exacto. Las decisiones del agente las toma
HappyRobot en vivo: llegan unos segundos después y pueden variar de un pase a otro. Eso también es la demo.

| Reloj real | Qué pasa (solo) | Qué dices / qué enseñas | Pregunta del reto |
|---|---|---|---|
| 0:00 | Pulsas **Start** en Mundo exterior. Llega el aviso rojo de AEMET. | «Esto es el mundo: llamadas al 112, redes, medios, sensores. El sistema no sabe qué viene.» Abre la crisis en el dashboard. | — |
| 0:15 | «Qué día más gris…» aparece **tachado: ruido descartado**. | Pantalla **Incidencias** (abajo, «avisos descartados como ruido»): HappyRobot (`PedroD-ingest-*`) percibe cada mensaje y el kernel los agrupa: varias llamadas sobre la misma residencia son **una** incidencia, con sus fuentes independientes contadas (veinte reenvíos de un bulo siguen siendo una sola voz «sin confirmar»). «De cien mensajes, quédate con tres incidencias.» | 1 · Qué información importa |
| 1:00–1:15 | 112 en Chiva (sev. 6) y aforo a 1.150 m³/s (sev. 7). El agente activa nivel, envía **ES-Alert a Chiva y a todo lo que tiene aguas abajo** y pide la UME. | Panel **Coordinación**: lee en voz alta un razonamiento. Pantalla **Zonas**: «Paiporta está seca, pero tiene una cuenta atrás de 38 minutos: decide sobre el grafo, no sobre el tiempo local.» | 2 · Qué va primero · 3 · A quién se avisa y cuándo |
| 1:15 | «Ordenar evacuación» queda **pendiente de aprobación** con temporizador; suena una **llamada entrante** para la Alcaldía de Paiporta. | Pulsa **Atender como Alcaldía de Paiporta** y habla con el agente: pregunta qué zonas, di «adelante». La acción pasa a ejecutada; `PedroD-crisis-response-coordination` registra lo que dijiste. | Interacción real · Control humano |
| 1:55–2:55 | El aforo **enmudece**. A los 20 min de escenario salta el reflejo de silencio. | **Últimos cambios**: «Aforos CHJ lleva 20 min en silencio, se asume escalada». «El silencio es una señal.» Abre **Ver plan, reflejos y lo aprendido**. | 6 · Cuándo tirar el plan |
| 2:05–2:30 | El agente ordena cortar una carretera a la Policía Local de Torrent: **no contesta** → escala sola a la Guardia Civil. | Pantalla **Contactos**: directorio, la entidad en rojo, la cadena de escalado. | 5 · Qué se hace ahora y quién |
| 2:36 | Rumor: «ha reventado la presa». | No pasa nada: fiabilidad baja, sin corroborar. «Un rumor no mueve recursos.» | 1 |
| 2:45 | 112: dos personas en un coche, garaje de Mestre Serrano (sev. 8, calle). **Salen 2 unidades al instante** (reflejo de triaje, sin esperar al LLM). | Panel **Respuesta · Bomberos**: unidades libres bajando, desplegadas por zona, embarcaciones. «Tres ambulancias y cinco sitios: aquí se ve a quién se deja esperando.» | 4 · Dónde van los recursos |
| 3:09 | **Se hunde el puente** de Sant Antoni. El plan queda **invalidado** y `PedroD-crisis-command` redacta otro. | Diálogo del plan: «Plan v1 invalidado: carretera cortada en Paiporta» → Plan v2 con otros objetivos. | 6 · Adaptarse |
| 3:30 | Residencia con 50 mayores (sev. 9). | Nueva prioridad P0; rescates reasignados. | 2 |
| 3:40 | **Tú** pulsas un «¿Y si…?» (p. ej. *Deja de contestar · Bomberos*). | «No está guionizado: el sistema se entera al llamar, escala y replanifica.» | Adaptación |
| 4:15 | Pulsas **Cerrar crisis**. | Lecciones: qué fuente fue ruido, quién no contestó, cuánto tardaron las aprobaciones. Inicia otra riada: en el diálogo del plan aparece **Aprendido de ejecuciones anteriores** y los priors ya vienen ajustados. | Bonus · Aprendizaje |

Cierre (15 s): «El agente propone; el kernel valida, pide firma para lo grave, ejecuta con contactos reales y, si algo falla,
escala y replanifica. Todo lo que decide queda con su evidencia y su porqué.»

## Si algo falla en directo

| Síntoma | Qué hacer | Por qué sigue funcionando |
|---|---|---|
| El túnel cae (callbacks 503) | Nada; `tunnel_watch.sh` lo reabre en ≤30 s | El estado viaja en cada disparo y el motor lee la salida del run en HappyRobot si el callback no llega |
| HappyRobot lento o caído | Nada | A los 25–45 s entra la percepción guionizada / el cerebro local, **etiquetados** como respaldo en la UI |
| No hay audio en la llamada | Aprueba con el botón **Aprobar** del panel de Autoridad | Botón, voz y enlace del email llaman a la misma función |
| Nadie atiende la llamada | Déjala sonar 40 s | «Sin respuesta» → escala a Delegación del Gobierno: también es demo |
| Se acaban los créditos | `VALTE_BRAIN=local backend/scripts/dev_server.sh 8010` | Todo el flujo funciona con el cerebro local |

## Variantes

- **Otra catástrofe en 30 s**: dashboard → *Iniciar catástrofe* → díctala (micrófono) o pulsa un ejemplo (Incendio/Apagón) →
  *Interpretar* → revisa lo que ha entendido → *Iniciar catástrofe* → en Mundo exterior escribe su código y elige Riada o Incendio → Start. El guion se genera a partir de esas zonas y sus retardos.
- **El plan va por detrás de la calle**: en cualquier panel de rol, *⚑ Reportar incidencia* → «Qué ha cambiado». Una línea
  basta: «se inunda Sedaví, 10.500 habitantes» mete la zona en el mapa con su cuenta atrás y su ayuntamiento; «nos llegan
  200 mantas» las suma al inventario; «se suma Cruz Roja con 12 voluntarios y 2 embarcaciones» da de alta a quien aparece;
  «ya hemos cortado el puente de la CV-36» queda como acción tuya y el agente deja de pedirla. Todo en el acto, y el
  coordinador despierta con el mundo nuevo.
- **Dos crisis a la vez**: otro Start. Cada una con su reloj y sus recursos.
- **Cada entidad ve lo suyo**: en un panel de rol, pulsa el segmento activo para cambiar de entidad; Recursos solo muestra lo propio.
