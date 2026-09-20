# Guion del video demo (1:30)

Objetivo: contar el proyecto a fondo para que se pueda juzgar
creatividad, resolucion de problemas y factura tecnica. Ritmo hablado:
unas 230 palabras. Grabar sobre el dashboard en vivo con una run a x60
ya avanzada, y cambiar de plano donde se indica.

---

**[0:00-0:12 — plano: mapa del dashboard con la cuenca]**

El 29 de octubre de 2024, la alerta a los moviles de Valencia llego a
las 20:11. El agua habia llegado una hora y media antes. Murieron 224
personas. La informacion existia desde por la mañana: fallo la
coordinacion. Esto es Valte: el sistema que faltaba esa tarde.

**[0:12-0:35 — plano: feed de señales y decisiones en vivo]**

Simulamos aquel dia con datos reales: el aviso rojo de AEMET, el
sensor del barranco del Poyo, cientos de llamadas al 112, tuits,
bulos. Agentes de HappyRobot atienden cada canal y convierten voz y
texto en señales estructuradas. Nuestro kernel puntua la confianza
cruzando canales, para que veinte copias de un bulo nunca pesen como
veinte testigos.

**[0:35-1:00 — plano: tarjeta de reflejos y log de decisiones]**

Y aqui la parte creativa: el agente coordinador no solo decide, se
programa a si mismo. Arma reflejos: reglas que el kernel ejecuta en
milisegundos, como "si el sensor supera el umbral, alerta a toda la
cuenca", o "si el sensor se queda en silencio, escala". El silencio
del sensor fue exactamente lo que paso en 2024, y aqui esta cubierto.
El kernel ademas no se fia del agente: valida jurisdicciones, lleva la
contabilidad de dotaciones en una base transaccional y rechaza lo
invalido explicando por que.

**[1:00-1:20 — plano: tarjeta de aprobacion; clic en Approve]**

El humano manda: pedir a la UME requiere aprobacion en pantalla, y
cada decision lleva su evidencia y su razonamiento auditables. Cuando
unos agricultores ofrecen ocho tractores por Twitter, el sistema los
registra como recurso y los usa cuando el agua baja.

**[1:20-1:30 — plano: cabecera con la hora de alerta]**

Resultado: alerta enviada horas antes que en 2024, todas las zonas
avisadas antes de su ola. Y todo el sistema es agnostico al escenario:
otra catastrofe es solo otra carpeta de datos. Esto es Valte.

---

Notas de grabacion:

- Lanzar la run con seed 42 unos 3 minutos antes de grabar para que el
  nivel 2 y la tarjeta de aprobacion esten en pantalla.
- Tener el panel de Runs de HappyRobot en una segunda pestaña por si
  se quiere enseñar la deliberacion del LLM.
- El clic de Approve debe hacerse en camara: es el requisito de
  supervision humana.
