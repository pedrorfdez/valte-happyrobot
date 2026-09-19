import random
import json
import re

TOWNS = ['Paiporta', 'Catarroja', 'Sedaví', 'Alfafar', 'Benetússer', 'Massanassa', 'Chiva', 'Utiel', 'Picanya', 'Torrent', 'Aldaia', 'Algemesí', 'Ribarroja', 'La Torre', 'Guadassuar', "L'Alcudia", 'Xirivella', 'Alaquàs', 'CV-36', 'V-30']

CRITICA = [
    ('¡Ayuda por favor! ¡El agua está entrando por las ventanas en {t} y estamos atrapados!', 'Tranquilícese, ¿tienen acceso a un piso superior o azotea?', '¡No, es una planta baja de ancianos! ¡El agua nos llega al pecho ya!', 'Suban sobre mesas. Priorizo su aviso a rescate acuático.'),
    ('¡Estoy subido al techo de mi coche en {t}! ¡La corriente me arrastra!', 'Señor, no intente nadar. Agárrese con toda su fuerza a un punto fijo.', '¡No hay nada! ¡Solo coches flotando! ¡Venid ya!', 'Estamos geolocalizando su terminal. Manténgase visible.'),
    ('¡Se ha caído el muro de la casa en {t}! ¡Mi marido ha quedado atrapado!', '¿Está consciente su marido? ¿Puede respirar?', '¡Apenas saca la cabeza! ¡El barro entra a borbotones!', 'Paso aviso de código rojo inmediato a bomberos.'),
    ('¡Estamos en la guardería de {t}! ¡Tres niños atrapados en el altillo!', '¿A qué nivel está el agua en el edificio?', 'Casi dos metros, ¡el techo falso cede!', 'Agrupaos en la zona más resistente. Despacho unidad urgente.'),
    ('¡El agua nos llega al cuello en el bajo en {t}! ¡Mis hijos encima del armario!', 'Mantenga a los niños en lo alto. ¿Hay alguna ventana hacia la calle?', '¡La persiana está bloqueada por los coches amontonados!', 'No gasten fuerzas golpeando, los equipos van con lanchas.'),
    ('¡La riada se lleva la furgoneta! ¡Estoy en {t} y no puedo salir!', 'Intente romper el cristal con el reposacabezas si el agua cubre la puerta.', '¡Lo intento pero no se rompe! ¡Entra muchísima agua!', 'Golpee en las esquinas del cristal, con fuerza. Enviamos ayuda.'),
    ('¡Ha reventado la puerta del garaje en {t}! ¡Mi mujer ha sido arrastrada!', '¿La ha perdido de vista? ¿Hacia dónde iba la corriente?', '¡Hacia el túnel! ¡No la veo, por favor rescatadla!', 'Unidades acuáticas peinando la zona. Resguárdese usted.'),
    ('¡Mi abuelo necesita oxígeno y el agua ha apagado el generador en {t}!', '¿Cuánto tiempo de autonomía le queda al equipo portátil?', '¡No tiene! ¡Está respirando muy mal, el agua ya cubre la cama!', 'Movilizamos lancha medicalizada. Incorpórele lo máximo posible.'),
    ('¡Estoy agarrado a un árbol en {t}! ¡El agua me llega al pecho!', 'Agárrese fuerte, no mire abajo. ¿Ve alguna edificación cerca?', '¡Solo un tejado a unos 10 metros, pero la corriente es brutal!', 'No se suelte. Rescate aéreo notificado para esa coordenada.'),
    ('¡El túnel de {t} está inundado! ¡Hay un autobús bajo el agua!', '¿Ve si hay pasajeros atrapados dentro del vehículo?', '¡Sí, hay gente golpeando los cristales desde dentro!', 'Bomberos en camino, no intente bajar al agua, la resaca es mortal.'),
    ('¡Se cae la escalera comunitaria! ¡El agua entra desde la rambla de {t}!', 'Suban al tejado o a la planta más alta inmediatamente.', '¡La escalera ha colapsado, no podemos subir más!', 'Rompan la pared del vecino si es pladur. Rescate en camino.'),
    ('¡El muro del patio en {t} acaba de ceder! ¡El agua nos lleva!', '¡Busquen un punto de anclaje, tuberías o pilares!', '¡Mi hijo se resbala! ¡Ayudaaaaa!', '¡Sujételo por la ropa! Efectivos en su calle.'),
    ('¡Mi mujer está de parto en {t} y el agua cubre toda la planta baja!', 'Túmbela en la zona más alta y seca, consiga toallas limpias.', '¡No hay zonas secas, estamos encima de la mesa del comedor!', 'SAMU activado con zodiac. Mantengan la calma, respiren.'),
    ('¡Nos ahogamos en {t}! ¡El techo se hunde y no podemos salir de la buhardilla!', '¿Tienen alguna herramienta para romper las tejas desde dentro?', '¡Solo un martillo! ¡El agua nos llega al cuello!', '¡Rompan el tejado ya! Abran un hueco para salir.'),
    ('¡Hay un hombre agarrado a una farola en {t} y se lo traga el agua!', '¿En qué calle exacta está ocurriendo?', '¡En la calle Mayor! ¡Se le resbalan las manos!', 'Equipos de proximidad avisados. No se tire a por él.'),
    ('¡Se ha derrumbado la casa de mi vecino en {t} con ellos dentro!', '¿Oye gritos o golpes de los ocupantes?', '¡Sí, lloran desde debajo de los cascotes y el agua sube!', 'Anotado código de derrumbe con atrapados. Ayuda en ruta.'),
    ('¡El barranco se ha desbordado en {t} y se lleva mi casa de madera!', 'Salgan de la casa inmediatamente si pueden hacer pie.', '¡La casa está flotando, nos arrastra hacia el puente!', 'Agárrense fuerte a la estructura. Helicóptero alertado.'),
    ('¡Estamos en el tejado en {t} y el agua ya llega a las tejas!', '¿Cuántas personas son? ¿Hay menores?', '¡Cinco, con dos bebés! ¡La antena se está cayendo!', 'Permanezcan sentados, distribuyan el peso. Ya vamos.'),
    ('¡Socorro en {t}, mi bebé se me ha resbalado y el agua tira mucho!', '¡No lo suelte! Atrápelo por cualquier prenda.', '¡Lo tengo por el abrigo pero me arrastra a mí también!', 'Apóyese en la pared, baje el centro de gravedad. Resiste.'),
    ('¡El agua ha reventado los cristales del supermercado de {t}!', '¿Hay gente herida por los cristales o ahogándose?', '¡Sí, hay ancianos flotando en los pasillos! ¡Es un infierno!', 'Múltiples unidades despachadas. Ayuden a los que floten.'),
    ('¡Ambulancia atrapada en {t}! ¡El paciente está en parada!', 'Sigan con maniobras RCP. ¿El agua entra al habitáculo?', '¡Sí, tenemos que subir al paciente al techo!', 'Apoyo de otra unidad SAMU por vía aérea en camino.'),
    ('¡Hospital comarcal inundado en {t}! ¡Pacientes de UCI en peligro!', '¿Tienen cortes eléctricos en los soportes vitales?', '¡Los SAIs están pitando, nos quedan 10 minutos!', 'Activado plan de catástrofes múltiples. Evacuación inminente.'),
    ('¡Mi hermana es ciega y está sola en casa en {t}! ¡Agua subiendo!', '¿Tiene contacto con ella por teléfono?', '¡Sí, pero está desorientada y el agua le cubre las piernas!', 'Dígale que se suba a la cama y no se mueva. Vamos a por ella.'),
    ('¡Hombre encerrado en el maletero de un coche flotando en {t}!', '¿Cómo sabe que hay alguien ahí?', '¡Se escuchan golpes desesperados desde dentro!', 'Facilíteme la matrícula si puede verla. Bomberos en ruta.'),
    ('¡Pareja de ancianos flotando encima de la cama en {t}!', '¿Está usted con ellos?', '¡Los veo desde mi balcón, el agua ha arrancado su fachada!', 'Tiradles cuerdas o sábanas si podéis alcanzarles. Rescate avisado.'),
    ('¡Chico atrapado en alcantarilla reventada en {t}!', '¿El chico respira? ¿Lo retiene la succión?', '¡Le tengo cogido del brazo pero la presión es inmensa!', 'No le suelte bajo ningún concepto. Vehículo de rescate cerca.'),
    ('¡Bombero fuera de servicio atrapado bajo un coche en {t}!', '¿Está consciente el compañero?', '¡Sí, pero el coche se hunde y lo aplasta!', 'Compañeros en camino, pasamos prioridad 1 absoluto.'),
    ('¡Autobús escolar atrapado, el agua entra por ventanillas en {t}!', '¿El conductor está evacuando a los niños al techo?', '¡Está intentándolo pero el agua tira a los niños!', 'Aviso masivo a rescate. Que aseguren a los niños con cinturones juntos.'),
    ('¡Tractor volcando en la rambla de {t}! ¡Conductor atrapado!', '¿El agua cubre la cabina del tractor?', '¡Está a punto de cubrirla entera!', 'Bomberos notificados, no intente acercarse por la corriente.'),
    ('¡Vecinos cayendo de la pasarela de {t}! ¡Se ha roto!', '¿Cuánta gente ha caído al agua?', '¡Por lo menos cuatro personas, se las lleva la riada!', 'Helicóptero notificado de urgencia.'),
    ('¡Mujer atrapada en el ascensor en el garaje de {t}!', '¿El agua ha llegado a la cabina del ascensor?', '¡La luz se apagó y oímos gritos de ahogo!', 'No abran las puertas del hueco, bomberos forzarán. Prioridad alta.'),
    ('¡Operario de grúa atrapado en la base en {t}! ¡La grúa cede!', '¿La grúa corre peligro de vuelco inminente?', '¡Los cimientos están cediendo por el barro!', 'Evacuen la zona de caída. Equipo de rescate en altura despachado.'),
    ('¡Riada se lleva un puente en {t} con coches encima!', '¿Han caído vehículos al cauce principal?', '¡Sí, tres coches han caído de golpe al abismo!', 'Catástrofe notificada a centro de mando. Todas las unidades alertadas.'),
    ('¡Mujer electrocutándose con los enchufes y el agua en {t}!', '¡No la toquen si están en el agua! ¿Pueden cortar la luz?', '¡El cuadro principal está sumergido, no podemos!', 'Aviso a compañía para corte zonal inmediato y a urgencias médicas.'),
    ('¡Persona con hipotermia severa aferrada a un balcón en {t}!', '¿Está consciente o pierde el conocimiento?', '¡Se está desmayando, se va a soltar!', 'Avisen a los vecinos de arriba que intenten agarrarla.'),
    ('¡Sótano inundado en 10 segundos en {t}! ¡No abre la puerta!', '¿Cuántas personas hay dentro?', '¡Mi hermano bajó a por el perro! ¡El agua presiona la puerta!', 'Rompan la puerta con mazas o hachas si tienen. Bomberos van.'),
    ('¡Coche de bomberos volcado por la riada en {t}!', '¿Compañeros heridos o atrapados?', '¡Dos han salido pero uno sigue en la cabina bajo el agua!', 'Prioridad absoluta, unidades de apoyo en camino inmediato.'),
    ('¡Familia rompiendo el techo para salir en {t}!', '¿Han conseguido abrir un agujero viable?', '¡Apenas cabe un brazo y el agua ya nos cubre!', 'Usen cualquier objeto contundente. Ayuda llegando a su tejado.'),
    ('¡Policía local pide rescate aéreo inmediato en {t}!', 'Recibido agente, confirme número de personas en peligro vital.', '¡Cinco personas colgadas de una valla que está cediendo!', 'Coordenadas copiadas, Puma en aproximación.'),
    ('¡Chica arrastrada al intentar cruzar la calle en {t}!', '¿Alguien ha podido lanzarle algo a lo que agarrarse?', '¡No, ha desaparecido bajo el agua turbia!', 'Búsqueda aguas abajo iniciada. Manténgase a salvo.'),
    ('¡El agua arranca la puerta y se lleva los muebles en {t}!', 'Suban encima de algo pesado que no flote fácilmente.', '¡Los muebles se han ido con mi abuela encima!', 'Equipos de salvamento peinando la calle. Agárrense fuerte.'),
    ('¡Paciente de diálisis cubierto por el agua en {t}!', '¿Está desconectado de la máquina?', '¡No podemos quitarle las vías y el agua sube!', 'Taponen las vías si pueden y elévenlo. Médicos informados.'),
    ('¡Anciana en silla de ruedas con el agua al cuello en {t}!', 'Levántenla entre varios si pueden.', '¡Pesa mucho y yo tengo la espalda rota!', 'Sosténganle la cabeza fuera. Equipo de rescate llegando al portal.'),
    ('¡Tejado de chapa volando, agua subiendo en {t}!', 'Si la chapa vuela, túmbense planos y protéjanse la cabeza.', '¡Las planchas cortan como cuchillas y no hay dónde ir!', 'Equipos de rescate pesado movilizados. Protéjanse como puedan.'),
    ('¡Coche hundiéndose en paso a nivel en {t}!', '¿Está el tren acercándose?', '¡Sí, las barreras están bajadas y el coche no sale!', 'Renfe notificada para paro de emergencia de trenes. Salgan del coche ya.'),
    ('¡Grupo de jóvenes atrapados en {t} en el cauce!', '¿Están dentro del cauce de hormigón?', '¡Sí, el nivel ha subido 3 metros en un minuto!', 'Corran hacia las escaleras de escape laterales más cercanas.'),
    ('¡Hombre con ataque al corazón en riada en {t}!', '¿Respira y tiene pulso?', '¡No tiene pulso! ¡Estamos rodeados de agua sucia!', 'Inicien masaje cardíaco inmediatamente. Helicóptero medicalizado en ruta.'),
    ('¡Coche flotando choca contra cristalera y entran en {t}!', '¿Han reventado el local donde están?', '¡Sí, el agua nos empuja hacia el fondo de la tienda!', 'Escapen hacia el almacén o zonas altas. Bomberos avisados.'),
    ('¡Casa de campo en {t} cediendo paredes por el río!', 'Salgan por la parte trasera opuesta a la corriente.', '¡Está bloqueado por árboles caídos!', 'Rompan ventanas y suban al punto más fuerte del techo.'),
    ('¡Bebé atrapado bajo un sofá que flota en {t}!', 'Levanten el sofá inmediatamente, busquen bajo el agua.', '¡No lo encontramos, el agua está negra!', 'Toquen con manos y pies. Equipos de rescate en su puerta casi.')
]

URGENTE = [
    ('Tenemos el garaje comunitario en {t} inundado, huele a gasolina.', '¿Nadie atrapado dentro?', 'No, nadie bajó. Pero tememos un incendio.', 'Nadie se acerque al hueco del ascensor. Aviso técnico.'),
    ('Atrapados en primer piso en {t}, sin agua y embarazada.', '¿Agua entrando a vivienda?', 'No, estancada en patio. Contracciones leves.', 'Aviso SAMU para evacuación preventiva.'),
    ('Camión cisterna volcado con derrame en {t}.', '¿Heridos en cabina?', 'Conductor fuera, vertido mezclándose con riada.', 'Guardia Civil y Bomberos notificados.'),
    ('Perros en caseta, agua a 80cm en {t}.', '¿Peligro para personas?', 'No, pero los animales se ahogarán.', 'Aviso a Protección Civil sección rescate animal.'),
    ('Trabajadores en nave industrial de {t} en altura, sin luz.', '¿Están seguros de la corriente?', 'Sí, pero sin comida ni agua, aislados.', 'Registramos posición para abastecimiento/evacuación.'),
    ('Grieta en edificio por choque de coche en {t}.', '¿Riesgo de colapso inminente visible?', 'Cruje bastante. ¿Evacuamos a azotea?', 'Sí, suban a la azotea de forma ordenada y esperen evaluación.'),
    ('Diabético necesita insulina en piso sin luz en {t}.', '¿Estado del paciente?', 'Estable pero lleva 12h sin dosis y no tenemos.', 'Aviso a sanitaria para dron o lancha de suministro.'),
    ('Anciana con fémur roto aislada en {t}.', '¿Necesita traslado urgente?', 'El dolor es insoportable, pero el agua no entra.', 'SAMU agendado para traslado en cuanto baje el nivel.'),
    ('Centro veterinario con animales ahogándose en {t}.', '¿Usted corre peligro?', 'Yo estoy en altillo, pero no llego a las jaulas.', 'Prioridad a personas, pero pasamos aviso a unidad canina/rescate.'),
    ('Ataque de ansiedad severo en aislada en {t}.', 'Páseme con ella al teléfono.', 'No respira bien, está hiperventilando.', 'Ayúdela a respirar en una bolsa de papel. Ayuda va en camino.'),
    ('Farmacia inundada, medicamentos perdidos en {t}.', '¿Hay personas sin medicación crítica?', 'Sí, vecinos piden oxígeno y sintrom urgentemente.', 'Centro logístico tomará su farmacia como punto de suministro.'),
    ('Bebé sin leche ni agua potable, aislados en {t}.', '¿Edad del bebé?', 'Cuatro meses, lleva un día sin tomar biberón.', 'Suministro aéreo o acuático programado para su bloque.'),
    ('Chisporroteo en contadores eléctricos inundados en {t}.', '¿Sale humo o hay fuego?', 'Chispazos grandes. Tenemos miedo de calambre general.', 'Desalojen las inmediaciones del cuarto. Iberdrola avisada.'),
    ('Árbol a punto de caer sobre vivienda en {t}.', '¿Hacia qué parte de la casa cae?', 'Hacia el tejado de las habitaciones.', 'Salgan de esas habitaciones, vayan a la parte opuesta. Bomberos en ruta.'),
    ('Rescate preventivo de camping en {t}.', '¿Cuánta gente hay aislada?', 'Unas 40 personas, el río amenaza con desbordar.', 'Despachamos autobuses de evacuación preventiva. Preparen a la gente.'),
    ('Inundación de 40cm, pérdidas materiales sin riesgo vital en {t}.', '¿Nadie en peligro?', 'No, pero lo hemos perdido todo.', 'Lamentamos la situación. Avisaremos a protección civil para limpieza posterior.'),
    ('Coche inmovilizado en balsa en {t}, sin riesgo.', '¿El agua arrastra al vehículo?', 'No, estamos estancados pero a salvo dentro.', 'Quédense dentro si no sube el agua. Grúas avisadas.'),
    ('Vecinos refugiados en azotea en {t}, con frío.', '¿Alguien con hipotermia grave?', 'Tiritan mucho, hay niños mojados.', 'Abríguense unos a otros. Rescate múltiple en camino.'),
    ('Residencia con generador estropeado en {t}.', '¿Equipos de soporte vital fallando?', 'Aún no, pero si se apaga habrá problemas.', 'Llevamos grupo electrógeno de emergencia a su posición.'),
    ('Requiere oxígeno en las próximas horas en {t}.', '¿Cuánta reserva le queda?', 'Tres horas máximo, no hay luz.', 'Suministro de bombonas priorizado para su dirección.'),
    ('Mujer mayor sola asustada en {t}.', '¿Entra agua a la casa?', 'Hay barro, pero no sube. Tengo mucho miedo.', 'Señora, cierre puertas y suba al sofá. Pronto irá la policía a verla.'),
    ('Familia pide mantas, han rescatado a 3 vecinos en {t}.', '¿Estado de los rescatados?', 'Congelados, les hemos dado nuestra ropa seca.', 'Gran labor. Efectivos van de camino con mantas térmicas.'),
    ('Rotura de tubería de gas en {t}.', '¿Fuerte olor en el exterior o interior?', 'En la calle, suena como un silbido muy fuerte.', 'No enciendan mecheros ni luces. Bomberos y compañía de gas notificados.'),
    ('Paciente oncológico no puede ir a quimio desde {t}.', '¿Es tratamiento diario crítico?', 'Sí, pierde el ciclo si no va hoy.', 'Activado transporte sanitario adaptado 4x4 o aéreo.'),
    ('Camionero varado en mediana en {t}.', '¿Agua en la cabina?', 'No, pero llevo 15 horas sin comer y mucho frío.', 'UME repartiendo mantas y raciones por su vía.'),
    ('Inundación planta comercial en {t}, refugiados.', '¿Cuántos están en la oficina?', 'Somos seis dependientes y tres clientes.', 'Quédense ahí hasta que baje el nivel. Seguros.'),
    ('Deslizamiento bloquea entrada a casa en {t}.', '¿Peligro de avalancha sobre la casa?', 'La casa parece estable pero no podemos salir.', 'Maquinaria pesada agendada para despejar. Quédense dentro.'),
    ('Vehículo bloquea acceso de ambulancia en {t}.', '¿Impide el paso total?', 'Sí, la ambulancia no puede pasar a por el enfermo.', 'Mandamos grúa municipal de urgencia para apartarlo.'),
    ('Fuga de agua incontrolable en edificio en {t}.', '¿Han cerrado la llave de paso general?', 'Está bajo el barro, imposible acceder.', 'Empresa de aguas notificada para corte exterior.'),
    ('Fractura de brazo en pueblo aislado de {t}.', '¿Hay hemorragia abundante?', 'No, solo deformidad y dolor agudo.', 'Inmovilicen el brazo con un cartón. Evacuación médica programada.'),
    ('Petición rescate caballos hípica en {t}.', '¿Cuántos animales?', 'Doce caballos, el agua les llega al lomo.', 'Bomberos forestales alertados para rescate equino.'),
    ('Colegio con niños aislados en {t}.', '¿Están seguros y calientes?', 'Sí, pero los padres llaman desesperados.', 'Avisen por grupos de padres que están a salvo. Llegaremos en horas.'),
    ('Vecinos piden revisión arquitectónica tras riada en {t}.', '¿Grietas nuevas de gran tamaño?', 'Bastantes en la fachada principal.', 'Técnicos municipales irán a valorar, no se acerquen a esa pared.'),
    ('Lodo bloquea portal en {t}, no pueden salir.', '¿Peligro dentro?', 'Ninguno, pero si hay fuego no podemos escapar.', 'Unidad de limpieza de calles priorizará su acceso.'),
    ('Hombre mayor con fiebre alta aislado en {t}.', '¿Temperatura exacta?', 'Casi 40, está delirando.', 'Médico al teléfono para indicaciones. SAMU notificado.'),
    ('Falta medicación psiquiátrica en {t}.', '¿Riesgo para sí mismo o terceros?', 'Se está poniendo agresivo por la falta de pastillas.', 'Contención verbal, mantengan distancia de seguridad. Ambulancia psiquiátrica en curso.'),
    ('Mujer necesita comida para 3 bebés en {t}.', '¿Tienen alternativa alguna?', 'Nada, se nos estropeó todo con el apagón.', 'Cruz Roja enviará raciones infantiles hoy mismo.'),
    ('Goteras masivas en nave de {t}, riesgo eléctrico.', '¿Han cortado la corriente general?', 'No sabemos dónde está el cuadro.', 'Salgan de la nave inmediatamente, riesgo de electrocución grave.'),
    ('Lanchas para evacuar a gente en primeros pisos en {t}.', '¿Por qué necesitan salir si el primer piso es seguro?', 'El edificio es muy viejo y tiembla con la corriente.', 'Entendido, posible riesgo de colapso. Lanchas en camino.'),
    ('Riesgo de hundimiento de acera en {t}.', '¿Socavón visible?', 'Sí, enorme, bajo nuestra finca.', 'Desalojen preventivamente hacia la parte trasera o azotea. Ingenieros avisados.'),
    ('Hospital comarcal parcial inundado en {t}.', '¿Afecta a generadores o urgencias?', 'Solo despachos y consultas externas de momento.', 'Bomberos enviarán motobombas pesadas.'),
    ('Herida leve por cristales en {t}.', '¿Hemorragia controlada?', 'Sí, le he puesto una venda, sangra poco.', 'Laven con agua limpia y acudan a ambulatorio cuando se pueda.'),
    ('Falta de agua potable en refugio en {t}.', '¿Cuánta reserva tienen?', 'Para hoy sí, pero para mañana nada.', 'Cisterna militar planificada para su zona.'),
    ('Carretera hundida en {t}.', '¿Coches caídos?', 'No, hemos frenado a tiempo, pero no se puede pasar.', 'Balicen la zona si es seguro. Tráfico desviando rutas.'),
    ('Pasajeros estación tren inundada en {t}.', '¿Seguros en los andenes altos?', 'Sí, pero hay pánico y algunos quieren caminar por las vías.', 'Eviten que bajen a las vías, riesgo eléctrico. ADIF avisado.'),
    ('Vecinos piden motobombas en {t}.', '¿Para garaje particular o vía pública?', 'Garaje particular, tenemos tres coches.', 'Priorizamos sótanos públicos, se enviarán cuando haya disponibilidad.'),
    ('Persona con hipotensión mareada en {t}.', 'Túmbenla y elévenle las piernas.', 'Ya lo hemos hecho, mejora un poco.', 'Dele agua con sal poco a poco si está consciente. SAMU en lista de espera.'),
    ('Riesgo caída poste eléctrico en {t}.', '¿Cables tocando el agua?', 'Aún no, pero el poste está a 45 grados.', 'No transiten por esa calle. Compañía eléctrica aislando sector.'),
    ('Asistencia persona sorda aislada en {t}.', '¿Tienen contacto visual con ella?', 'Desde la ventana de enfrente, no se entera de los avisos por megafonía.', 'Hagan señales luminosas. Rescatadores irán a su puerta y llamarán fuerte.'),
    ('Evacuación preventiva campamento en {t}.', '¿Están en zona inundable?', 'A escasos metros del río que sube.', 'Muevan a todos a la loma alta más cercana ya mismo.')
]

RUIDO = [
    ('¿Hola? ¿Emergencias? ...', 'Dígame, 112.', 'Espera que no te oigo nada... [Corte]', '...'),
    ('Llevamos 4 horas sin luz en {t}.', 'Contacte con Iberdrola. Emergencias vitales solo.', '¡Es una vergüenza, se me pudre la comida!', 'Libere la línea por favor. Buenas noches.'),
    ('¿Mañana funciona el metro en {t}?', 'Consulte redes oficiales. No saturar.', 'Es que tengo cita médica.', 'Siga comunicados. Mantenga línea libre.'),
    ('[Respiración agitada] ...', '112 Emergencias, le escucho.', '[Ruido de pasos en agua y corte]', '...'),
    ('¿Seguro del coche en {t}?', 'Consorcio de seguros. Esta línea es auxilio urgente.', '¿Pero qué papeles piden?', 'No disponemos de esa info. Adiós.'),
    ('Alarma de protección civil tarde en {t}.', 'Entendemos su enfado. ¿Tiene emergencia vital?', '¡Dimisión es lo que toca!', 'Procedo a cortar la llamada. Gracias.'),
    ('Contenedor tapando vado en {t}.', 'Aviso a ayuntamiento. ¿Peligro para personas?', 'No, pero no puedo sacar el coche.', 'No es emergencia. Corto.'),
    ('Retenciones para Madrid desde {t}.', 'Consulte DGT. Viajes desaconsejados.', 'Tengo que llevar a mi cuñado.', 'No viaje. Vía libre por favor.'),
    ('[Ruido de lluvia]', '112, ¿cuál es su emergencia?', 'Se me va la cobertura... [Pitido]', '...'),
    ('¿Abren los colegios en {t}?', 'Consulte ayuntamiento o educación.', 'Ah, vale.', 'Línea solo urgencias.'),
    ('¿Agua del grifo potable en {t}?', 'Informarán autoridades municipales. Evítela por precaución si está turbia.', 'Gracias.', 'De nada.'),
    ('¿Supermercado abierto en {t}?', 'Desconocemos comercios abiertos. Evite salir.', 'Quería comprar pan.', 'No salga, alerta máxima.'),
    ('[Llamada muda de bolsillo]', '112, dígame.', '[Conversaciones de fondo y risas]', '...'),
    ('¡Sinvergüenzas, llevo 20 min esperando en {t}!', 'Líneas saturadas por la riada. ¿Emergencia?', 'Solo quería quejarme.', 'Adiós.'),
    ('¿A qué hora para de llover en {t}?', 'Mire el radar meteorológico de AEMET.', 'Es que no tengo internet.', 'Seguirá lloviendo. Refúgiese.'),
    ('[Interferencias severas]', '112, dígame.', '[Crujidos y corte]', '...'),
    ('¿Mi jefe me obliga a ir a trabajar en {t}?', 'La alerta roja exime de desplazamientos peligrosos. Consulte sindicatos.', 'Es que me despide.', 'No arriesgue su vida. Adiós.'),
    ('¿El paquete de Amazon llegará hoy a {t}?', 'Servicios de paquetería suspendidos.', 'Jo, era urgente.', 'Línea vital. Cortamos.'),
    ('¿Huelga de trenes en {t}?', 'Servicio suspendido por inundación, no huelga.', 'Ah, pensaba que era huelga.', 'Mantenga línea libre.'),
    ('Entra agua por ventana del baño en {t}.', 'Ponga toallas y recoja con cubos. ¿Peligro vital?', 'No, pero ensucia todo.', 'No es urgencia 112.'),
    ('¿Han cancelado el partido en {t}?', 'Consulte información deportiva oficial.', 'Vale, gracias.', '...'),
    ('¿Dónde pido justificante de trabajo en {t}?', 'A su ayuntamiento mañana.', '¿Seguro?', 'Sí. Adiós.'),
    ('Mi perro tiene miedo a los truenos en {t}.', 'Manténgalo en zona interior con música calmante. No urgencia vital.', 'Pobrecillo.', 'Cuelgo.'),
    ('Limpie alcantarillas de mi calle en {t}.', 'Se avisará a limpieza vial. No es emergencia vital.', 'Huele mal.', '...'),
    ('La vecina me ha tirado agua de su terraza en {t}.', 'Llame a policía local por conflicto vecinal.', 'Es que lo hace aposta.', 'No sature el 112.'),
    ('¿Puedo ir a Bonaire desde {t}?', 'Accesos cortados y peligroso. Quédese en casa.', 'Quería ir al cine.', 'Prohibido desplazarse.'),
    ('[Corte directo]', '112...', '[Corte]', '...'),
    ('Los bomberos hacen mucho ruido en {t}.', 'Están trabajando en rescates vitales, señora.', 'No me dejan dormir.', 'Sin comentarios. Adiós.'),
    ('¿Dónde reparten sacos de arena en {t}?', 'Contacte con Protección Civil municipal.', '¿Me los traen?', 'No, debe recogerlos. Cuelgo.'),
    ('¿Hay toque de queda en {t}?', 'Hay alerta roja que desaconseja salir.', '¿Me multan?', 'Proteja su vida. Adiós.'),
    ('Mi internet Movistar no va en {t}.', 'Caída masiva de redes. Espere restablecimiento.', 'Quería ver Netflix.', 'Cuelgo.'),
    ('Me han robado la antena de la tele en {t}.', 'Habrá volado por el temporal. Llame a seguro mañana.', 'Creo que fue el vecino.', 'No es urgencia.'),
    ('¿Es verdad el bulo de la presa en {t}?', 'Presa estable. Siga cuentas oficiales, no Whatsapp.', 'Me asustaron.', 'Cuelgo.'),
    ('¿A qué hora abren bancos en {t}?', 'Desconocemos apertura de comercios.', 'Quería efectivo.', 'Línea urgencias.'),
    ('Se ha volado mi sombrilla en {t}.', 'No salga a buscarla. ¿Ha herido a alguien?', 'No, pero costaba 100 euros.', '...'),
    ('[Voz de niño] Hola, mi papá no está...', '¿Estás solo? ¿Pasa algo malo?', 'Mentira, te he engañado jajaja', 'Línea de emergencias, no juegues.'),
    ('Quiero denunciar a la alcaldesa de {t}.', 'Acuda al juzgado o cuartel de guardia. 112 es auxilio vital.', 'Es culpa suya la inundación.', 'Cuelgo.'),
    ('¿Me cubre seguro si cae el árbol en {t}?', 'Pregunte a su aseguradora.', 'No cogen.', '112 tampoco.'),
    ('[Silencio 10 segundos]', '112, dígame...', '...', 'Corto comunicación.'),
    ('Música de espera lejana en {t}.', '112, ¿hola?', '[Música de retención]', '...'),
    ('¿Aeropuerto abierto para París desde {t}?', 'Consulte AENA. Muchas cancelaciones.', 'Tengo vuelo a las 8.', 'Línea urgencias.'),
    ('Charco grande en puerta de mi casa en {t}.', '¿Entra agua o hay peligro?', 'Me mojo los zapatos al salir.', 'No es emergencia.'),
    ('¿Puedo salir a correr en {t}?', 'Totalmente desaconsejado, riesgo extremo.', 'Pero no llueve ahora.', 'Órdenes de quedarse en casa.'),
    ('¿Dónde presento queja luz en {t}?', 'Iberdrola atención cliente o Consumo.', 'Vale.', '...'),
    ('¿Mañana mercadillo en {t}?', 'Actividades al aire libre suspendidas.', 'Quería comprar naranjas.', '...'),
    ('[Ruido de masticar]', '112, dígame.', '[Crujido de patatas]', 'Oiga... corto.'),
    ('¿Suspenden las fallas por esto en {t}?', 'Estamos en noviembre. No sature la línea.', 'Era por saber.', '...'),
    ('Me he manchado zapatos de barro en {t}.', '...', 'Culpa del ayuntamiento.', 'Corto por línea saturada.'),
    ('¿Agua de lluvia buena para plantas en {t}?', '...', '¿Sabe usted?', 'Emergencias vitales solo.'),
    ('La grúa de mi seguro no viene a {t}.', 'Grúas paradas por colapso vial.', 'Se me rompió el embrague.', 'Espere en lugar seguro.')
]

def generate_list(template_list):
    result = []
    for t in template_list:
        town = random.choice(TOWNS)
        d = []
        d.append({"hablante": "operador", "texto": t[1]})
        d.append({"hablante": "llamante", "texto": t[0].format(t=town)})
        d.append({"hablante": "operador", "texto": t[3]})
        d.append({"hablante": "llamante", "texto": t[2].format(t=town)})
        result.append(d)
    return result

c = generate_list(CRITICA)
u = generate_list(URGENTE)
r = generate_list(RUIDO)

# Read file, replace strings
with open('c:/Users/javie/Desktop/hackspain/valte-happyrobot/voicedata/prompts.py', 'r', encoding='utf-8') as f:
    content = f.read()

c_str = json.dumps(c, ensure_ascii=False, indent=4)
content = re.sub(r'MOCK_DIALOGUES_CRITICA\s*=\s*\[.*?\]', 'MOCK_DIALOGUES_CRITICA = ' + c_str, content, flags=re.DOTALL)

u_str = json.dumps(u, ensure_ascii=False, indent=4)
content = re.sub(r'MOCK_DIALOGUES_URGENTE\s*=\s*\[.*?\]', 'MOCK_DIALOGUES_URGENTE = ' + u_str, content, flags=re.DOTALL)

r_str = json.dumps(r, ensure_ascii=False, indent=4)
content = re.sub(r'MOCK_DIALOGUES_RUIDO\s*=\s*\[.*?\]', 'MOCK_DIALOGUES_RUIDO = ' + r_str, content, flags=re.DOTALL)

with open('c:/Users/javie/Desktop/hackspain/valte-happyrobot/voicedata/prompts.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("prompts.py updated successfully with 50 variations for each category.")
