# Extensión del navegador

El Asistente Seguro protege lo que usted consulta **dentro** de la plataforma. Pero
muchas personas usan también asistentes de IA públicos en el navegador, y ahí los datos
personales saldrían sin ninguna protección.

Para cubrir ese hueco existe la extensión del navegador.

## Qué hace

La extensión vigila lo que usted escribe en los asistentes de IA web (por ejemplo,
ChatGPT o Claude) y **enmascara los datos personales antes de que salgan de su
navegador**. Si escribe un nombre o un DNI en una de esas páginas, lo que se envía al
servicio externo es una etiqueta neutra, no el dato real.

Dos ideas importantes:

- **Su organización decide qué se enmascara.** Las reglas no las configura usted: son las
  mismas políticas de protección de datos que aplica la pasarela.
- **El uso queda registrado.** Igual que las consultas hechas desde el Asistente Seguro,
  la actividad a través de la extensión se audita, para que la organización pueda
  acreditar un uso responsable de la IA.

## Cómo se obtiene

La extensión **no se descarga de una tienda de complementos**. La distribuye e instala su
administrador, junto con las instrucciones concretas para el navegador aprobado en su
organización.

Si cree que necesita la extensión y no la tiene, escriba a su administrador.

Para que la extensión pueda hablar con la pasarela, el equipo tiene que **confiar en el
certificado** de la instalación. De eso se encarga su administrador —está descrito en
[Confiar el certificado en los equipos](../admin/certificado.md)—; si la extensión no
conecta y la dirección es la correcta, ése suele ser el motivo.

!!! note "No la instale por su cuenta"
    Solo la copia que le facilite su administrador está configurada con las políticas de
    su organización. Cualquier complemento de aspecto similar obtenido por otra vía no
    es esta herramienta.

## Qué esperar al usarla

- **Trabajará usted igual que siempre.** Escribe en el asistente de IA web con
  normalidad; la protección actúa en segundo plano.
- **Es una red de seguridad, no un permiso.** Que la extensión enmascare datos no
  significa que cualquier información pueda salir hacia un servicio externo. Siga
  aplicando las normas de su organización sobre qué se puede consultar y dónde.
- **Para el trabajo con datos sensibles, use el Asistente Seguro.** Es el canal en el que
  su organización tiene control completo del modelo, de las políticas y de la auditoría.

## Si algo no funciona como espera

Avise a su administrador e indíquele:

1. En qué página o asistente de IA ocurrió.
2. Qué esperaba que sucediera y qué sucedió.
3. La fecha y la hora aproximadas, para que pueda localizar el registro.

No intente reinstalar ni reconfigurar la extensión por su cuenta.
