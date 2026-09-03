Hola Tomy, hola Noe 👋

Les cuento las mejoras que subimos hoy al portal (`eleavdmia:8095`), ya están activas —
no hace falta hacer nada de su lado:

**Diseño nuevo**
El Hub cambió a un look claro con el logo de EleIA, más ordenado y prolijo. Los espacios
de trabajo, hilos y documentos que ya tenían cargados siguen todos ahí, no se perdió nada.

**Los hilos ya no "se olvidan" la conversación**
Antes, si entraban a un hilo, se iban a otro y volvían, el historial de mensajes
desaparecía de la pantalla (aunque seguía guardado). Ya está arreglado — el historial
real se recarga solo.

**Ahora el chat responde con el dato real, no con un código**
Esta es la más importante. Cuando suben un documento con un dato personal (DNI, email,
teléfono, CBU, un nombre), el sistema lo protege automáticamente antes de que lo vea el
modelo de IA — hasta ahí ya funcionaba. Lo que faltaba: cuando alguien preguntaba por ese
dato en el chat, la respuesta mostraba un código en vez del valor real (algo como
`[DNI_0_a03c]`). Ya está resuelto: el chat ahora responde con el dato real, como
corresponde, manteniendo la misma protección en todo momento.

**Importante**: esto aplica a los documentos que suban **de ahora en adelante**. Los que
ya estaban cargados de antes van a seguir mostrando esos códigos si les preguntan por un
dato protegido — no hace falta volver a subirlos salvo que necesiten consultar
específicamente ese dato.

Cualquier cosa rara que vean, avisen y lo vemos. Gracias por la paciencia mientras
seguimos afinando esto 🙌
