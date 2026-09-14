# Eleia Hub: espacios, planillas, presentaciones y protección

Guía para el administrador de una instancia con **Eleia Hub** activo: el chat con documentos,
los espacios de planillas (cálculo exacto sobre Excel/CSV) y la generación de presentaciones.
Cubre el aislamiento entre personas, el gasto, la protección de datos y la administración de
plantillas.

**Para quién**: el tenant admin que opera la instancia y responde consultas de las personas
que usan Eleia Hub.

!!! note "Leyenda de estado"
    🟢 **HOY** — funciona y está verificado · 🔵 **OBJETIVO** — roadmap, no implementado.

---

## Espacios de trabajo: quién ve qué 🟢

Cada persona en Eleia Hub ve **únicamente** los espacios de los que es miembro. Al entrar sin
ningún espacio asignado, ve un estado vacío con dos acciones: crear uno propio o pedirle a su
administrador que la agregue a uno existente.

```mermaid
graph LR
    A[Ana] -->|dueña| E1[Espacio: Contabilidad]
    A -->|miembro| E2[Espacio: NDA]
    L[Luis] -->|dueño| E3[Espacio: RRHH]
    E1 -. sin acceso .-> L
```

Quien crea un espacio queda como su dueña y puede, desde el panel "Miembros" del espacio:

- Ver la lista de miembros y su rol (dueño / miembro).
- Agregar a otra persona por nombre de usuario.
- Quitar a un miembro.
- Transferir la propiedad del espacio.

Un miembro que no es dueño ve la misma lista en modo solo lectura. Dentro de un espacio, cada
persona ve únicamente **sus propios hilos** de conversación — el "hilo principal" del espacio
también es suyo, nunca compartido.

Intentar abrir un espacio ajeno por una URL o identificador conocido responde "No tenés acceso
a este espacio" sin cargar ningún dato — nunca revela si el espacio existe.

### Espacios "sin asignar" tras una migración 🟢

Una instalación que ya tenía espacios de trabajo antes de esta funcionalidad los deja, al
actualizar, en estado "sin asignar": nadie es miembro todavía. El admin los ve y les asigna un
dueño desde:

- El panel de administración (Guardian), en **Usuarios & Presupuestos → Espacios sin
  asignar**.
- El propio Eleia Hub, en el botón "Sin asignar" del encabezado (visible solo para roles
  administradores).

## Presupuesto: autoservicio, nunca una sesión de admin 🟢

Eleia Hub lee el presupuesto de **cada persona con su propia sesión** — nunca con una cuenta de
administrador de fondo. Antes de enviar una pregunta o subir un documento, el Hub verifica el
presupuesto disponible; si está agotado, bloquea localmente con el mismo mensaje neutro que
usaría un rechazo real del servidor ("Alcanzaste tu presupuesto. Contactá a tu administrador"),
para que la persona nunca note la diferencia entre un bloqueo local y uno del backend.

En el panel de administración, **Costos → Gasto por usuario** ya incluye la actividad que una
persona hizo dentro de sus espacios (antes quedaba invisible bajo la cuenta de servicio del
Hub).

## Protección de documentos: en el firewall, no en el Hub 🟢

Desde la spec 050 (12-sep-2026), Eleia Hub **no enmascara** los documentos antes de subirlos.
Los archivos viven crudos en el motor de documentos, dentro del servidor de la instalación, y
nunca salen de ahí. La protección ocurre en el firewall de Eleia Guardian: cada vez que el
motor de documentos arma una pregunta con fragmentos de un documento y la envía al modelo, el
firewall detecta y enmascara los datos personales antes de que salgan al proveedor, y los
restituye en la respuesta. En el panel, **Costos → Protección** muestra las entidades
enmascaradas por consulta, atribuidas a la cuenta de servicio del motor de documentos.

## Planillas: cálculo exacto sobre Excel y CSV 🟢

La pestaña **Planillas** tiene sus propios espacios, con la misma regla de membresía que los de
documentos, pero nunca mezclados. En cada espacio se suben una o varias planillas (`.csv`,
`.xlsx`; cada hoja es una tabla; hasta 50 MB) y se pregunta en lenguaje natural. La respuesta es
un cálculo real: el modelo escribe una consulta de solo lectura, el motor la valida y la ejecuta,
y la persona ve la respuesta, la tabla y la consulta plegada. Cruzar archivos entre sí es nativo.

- El encabezado real se detecta aunque la planilla tenga título y notas arriba.
- **Diccionario de datos**: un clic en cualquier columna permite escribir qué significa (por
  ejemplo, `Ce.` = "centro logístico", o "vacío = pendiente de decisión"). Lo que se escribe
  viaja al modelo en cada pregunta de ese espacio. Conviene cargarlo en planillas exportadas de
  SAP u otros sistemas con encabezados abreviados.
- Preguntas que exigen un juicio que los datos no contienen (por ejemplo "¿hay nombres de
  personas?") se responden como "no se puede responder con estos datos": eso lo hace el detector
  de Guardian, no el SQL.
- Las planillas viven crudas en el motor, dentro del servidor; solo lo que va al modelo pasa por
  el firewall.

## Presentaciones y "Mis archivos" 🟢

Desde cualquier respuesta, del chat o de planillas, el botón **Crear presentación** abre un
formulario: título, plantilla modelo, cantidad de diapositivas, formato (PowerPoint o PDF),
indicaciones y, opcionalmente, **sumar datos de una planilla** con una pregunta. Tarda entre uno y
dos minutos. El archivo queda en **Mis archivos**, visible y descargable solo por quien lo generó.

### Plantillas modelo y plantilla corporativa 🟢

El formulario ofrece las plantillas integradas y, primero, las **propias**. Para crear una
plantilla propia a partir del PowerPoint corporativo, un administrador abre la pestaña
**Plantillas** (o `http://<host>:8097/templates`, con la misma sesión del Hub), sube el `.pptx`,
acepta las fuentes de respaldo y confirma. El motor analiza cada diapositiva con un modelo con
visión y arma los layouts; con 6 diapositivas tarda unos 5 minutos. Si un layout falla, se
repite el flujo. Esa pantalla es solo para administradores; nadie más llega al motor.

## Varias personas: qué está verificado 🟢

Con dos usuarios reales: ninguno ve los espacios, hilos, planillas ni archivos generados del
otro; al pedirlos por id recibe "sin acceso"; al agregar a la persona como miembro, accede. El
administrador del tenant accede a todos los espacios por su rol.

## Ninguna marca de motor visible 🟢

Ni el Hub ni el panel muestran en ningún punto el nombre del motor de documentos, del
proveedor de detección de datos personales, ni del motor de enrutamiento de modelos que
Eleia usa internamente — todos los mensajes de error y textos de interfaz usan un vocabulario
neutro ("el servicio de documentos", "el servicio de protección de datos"). Una prueba
automática (`tools/check-branding-neutral.js`, corrida en CI) verifica que ningún término
prohibido aparezca en el HTML servido ni en el build de producción del panel.
