# Cómo se protegen sus datos

Cuando usted consulta a la IA a través de esta plataforma, lo que escribe no viaja tal
cual. Antes de salir, los datos personales se sustituyen por etiquetas; cuando vuelve la
respuesta, se restauran para que usted la lea completa. Esta página explica ese viaje sin
tecnicismos, con un ejemplo real.

## El viaje de una consulta, paso a paso

### 1. Usted escribe con normalidad

Supongamos que necesita un borrador de correo y escribe algo así:

> Redacta un borrador de email para la empresa Ejemplo SL. El contacto es Lucía Pérez,
> DNI 12345678Z, teléfono 612 345 678. Quieren información sobre certificados de origen
> para exportar a Francia.

Ha escrito un nombre, un DNI y un teléfono. No pasa nada: es exactamente lo que la
plataforma está preparada para gestionar.

### 2. La plataforma detecta y enmascara los datos personales

Antes de que su texto salga hacia el modelo de IA, la pasarela localiza los datos
personales y los sustituye por etiquetas neutras:

| Lo que usted escribió | Lo que recibe el modelo |
| --- | --- |
| Lucía Pérez | `[PERSON_0]` |
| 12345678Z | `[ES_NIF_0]` |
| 612 345 678 | `[PHONE_NUMBER_0]` |
| Francia | `[LOCATION_0]` |

El modelo de IA nunca llega a ver el nombre, el documento ni el teléfono. Trabaja sobre
un texto que conserva el sentido de la frase, pero no la identidad de nadie.

### 3. Esto es lo que realmente sale

No es una promesa: queda registrado. Su administrador puede ver, en el registro de
tráfico de la organización, el texto exacto que salió hacia el modelo — ya enmascarado.

![Registro de tráfico mostrando el texto enviado al modelo con los datos personales sustituidos por etiquetas](../assets/screenshots/41-firewall-vivo.png)

Fíjese en el recuadro inferior de la imagen: donde había un nombre, un DNI y un teléfono
ahora hay `[PERSON_0]`, `[ES_NIF_0]` y `[PHONE_NUMBER_0]`. Arriba, el propio evento indica
cuántos datos personales se enmascararon.

### 4. La respuesta vuelve con sus datos restaurados

Cuando el modelo contesta, la plataforma deshace la sustitución **dentro de su propia
organización**: donde el modelo escribió `[PERSON_0]`, usted lee "Lucía Pérez".

Por eso la respuesta le resulta natural y directamente utilizable, aunque el modelo nunca
haya conocido los datos reales.

### 5. Queda constancia, sin guardar lo que escribió

Cada consulta se registra para poder acreditar el uso responsable de la IA: quién
consultó, cuándo, qué modelo se usó, qué protecciones se aplicaron y cuántos datos
personales se enmascararon.

!!! note "El registro no guarda su texto en claro"
    La auditoría se conserva **sin el texto del prompt ni datos personales en crudo**.
    Sirve para demostrar el cumplimiento, no para leer lo que usted escribió.

## Si su petición sale BLOQUEADA

A veces una consulta no llega a enviarse y aparece marcada como bloqueada. Conviene
entender qué significa:

- **No es un fallo técnico ni un error suyo.** La plataforma funcionó exactamente como
  debía.
- **Es una política de su organización.** Su organización define qué contenidos no pueden
  salir hacia un modelo de IA, y esa consulta encajaba en una de esas reglas.
- **La consulta no salió.** Nada de lo que escribió llegó al modelo.

Qué hacer:

1. Revise si puede reformular la consulta sin el contenido restringido. Muchas veces la
   pregunta de fondo se puede plantear en términos generales.
2. Si necesita realmente hacer esa consulta para su trabajo, **contacte a su
   administrador**. Él conoce las políticas vigentes y puede valorar el caso.

!!! warning "No intente sortear un bloqueo"
    Trocear el texto, cambiar el formato o usar otro canal para enviar lo mismo va contra
    la política de su organización, y el intento también queda registrado. Ante la duda,
    pregunte antes.

## Preguntas frecuentes

**¿Puedo escribir datos de clientes o de expedientes?**
Puede escribir con normalidad: la protección actúa sola. Aun así, aplique el criterio de
siempre — comparta solo lo necesario para obtener la respuesta que busca.

**¿Cómo sé que funcionó?**
Mire la etiqueta *"N datos personales protegidos"* bajo cada respuesta. Si ve un número
mayor que cero, se enmascararon datos en esa consulta.

**¿Y si veo un cero cuando esperaba protección?**
Puede que su texto no contuviera datos personales reconocibles. Si cree que sí los
contenía, avise a su administrador: él puede revisar las reglas de detección.

**¿Quién decide qué se enmascara y qué se bloquea?**
Su organización, a través del administrador. Las reglas no son universales: se configuran
según el uso y el marco legal de cada equipo.
