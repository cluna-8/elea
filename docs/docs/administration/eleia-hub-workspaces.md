# Eleia Hub: espacios, presupuesto y protección de documentos

Guía para el administrador de una instancia con **Eleia Hub** (el chat de espacios de trabajo
con documentos) activo. Cubre el aislamiento de espacios entre personas, cómo se ve el gasto
de cada una, y qué avisa la interfaz sobre la protección de datos personales en los documentos
que se suben.

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

## Ninguna marca de motor visible 🟢

Ni el Hub ni el panel muestran en ningún punto el nombre del motor de documentos, del
proveedor de detección de datos personales, ni del motor de enrutamiento de modelos que
Eleia usa internamente — todos los mensajes de error y textos de interfaz usan un vocabulario
neutro ("el servicio de documentos", "el servicio de protección de datos"). Una prueba
automática (`tools/check-branding-neutral.js`, corrida en CI) verifica que ningún término
prohibido aparezca en el HTML servido ni en el build de producción del panel.
