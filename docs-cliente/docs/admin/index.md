# Primeros pasos como administrador

Esta página le lleva desde el primer acceso a la plataforma hasta dejarla lista para que
su organización empiece a usarla: conocerá el panel, sabrá dónde se hace cada cosa y
completará una puesta en marcha mínima.

## Entrar por primera vez

En una instalación nueva **no existe una contraseña de fábrica**. El primer acceso con el
usuario `admin` es el que **crea** la cuenta de administrador con la contraseña que usted
escriba en ese momento.

1. Abra en el navegador la dirección de su instalación. Verá la pantalla de acceso.
2. Escriba `admin` en **Usuario**.
3. Escriba en **Contraseña** la contraseña que quiera dejar fijada para el
   administrador. Debe tener **al menos 12 caracteres**.
4. Pulse **Ingresar al Panel**.

![Pantalla de acceso con los campos Usuario y Contraseña y el botón Ingresar al Panel](../assets/screenshots/01-login.png)

A partir de ese momento, los accesos siguientes son un inicio de sesión normal: la misma
contraseña que escribió la primera vez.

!!! warning "Haga este primer acceso usted, y hágalo pronto"
    Mientras la cuenta de administrador no exista, cualquiera que llegue a la dirección
    de la instalación puede crearla escribiendo la contraseña que quiera y quedarse con
    el control del panel. Realice el primer acceso en cuanto reciba la dirección, desde
    un equipo de confianza, y elija una contraseña larga y única. No la comparta ni la
    reutilice: la cuenta `admin` puede ver la auditoría, emitir llaves de acceso y
    restablecer la contraseña de cualquier persona.

## Recorrido del panel

El menú lateral izquierdo es fijo y agrupa todo lo que puede hacer un administrador:

| Sección | Para qué sirve |
| --- | --- |
| **Panel Principal** | Vista de conjunto: peticiones, costo total, incidentes de datos personales, bloqueos, modelos más usados y estado del sistema. |
| **Playground** | Un espacio de prueba para lanzar consultas a un modelo y ver, paso a paso, qué capas de seguridad se aplicaron. |
| **Firewall en vivo** | El flujo de peticiones en tiempo real: cuáles se permitieron, cuáles se bloquearon y qué texto —ya enmascarado— salió hacia el modelo. |
| **Modelos & Ollama** | Los modelos de IA disponibles en la pasarela y el catálogo desde el que añadir otros. |
| **Costos** | El consumo económico acumulado y su reparto. |
| **Usuarios & Presupuestos** | Alta de equipos y personas, llaves de acceso, límites de consumo y opciones de autenticación. |
| **Gobernanza** | La configuración vigente de las capas de seguridad que se aplican a cada petición. |
| **Seguridad y Guardianes** | Los controles que inspeccionan el contenido y su actividad. |
| **Políticas de Cumplimiento** | Las reglas de tratamiento de datos que la organización declara y aplica. |
| **Logs de Auditoría** | El registro histórico de la actividad, conservado sin texto de prompt ni datos personales en claro. |
| **Documentación** | Acceso a esta guía desde el propio panel. |

Abajo a la izquierda, bajo el menú, aparece siempre su tarjeta de usuario con el nombre
de la cuenta, el rol y el botón **Salir**.

## Cambiar su contraseña

1. En la parte inferior del menú lateral, pulse **Cambiar mi contraseña**.
2. Introduzca la contraseña nueva (mínimo 12 caracteres) y confirme.

Cualquier persona con cuenta en la plataforma dispone de este mismo botón, así que puede
pedir a los usuarios que cambien la contraseña inicial que usted les entregó.

## Restablecer la contraseña de otra persona

Si un miembro del equipo pierde su contraseña, usted puede asignarle una nueva:

1. Vaya a **Usuarios & Presupuestos** y abra la pestaña **Usuarios & Equipos**.
2. Localice a la persona en la tabla de miembros.
3. Pulse **Restablecer contraseña** y fije una contraseña nueva.
4. Entréguesela por un canal seguro y pídale que la cambie desde
   **Cambiar mi contraseña** en cuanto entre.

!!! note "Nunca por correo ni por chat abierto"
    Las contraseñas iniciales y las restablecidas deben entregarse en persona o por un
    canal seguro acordado, y cambiarse en el primer acceso.

## Checklist de puesta en marcha

Complete estos cinco pasos y la plataforma queda operativa:

1. **Cree el primer equipo.** Los equipos son la unidad sobre la que se reparten el
   presupuesto y el perfil de cumplimiento. → [Personas y equipos](usuarios.md)
2. **Registre a las personas.** Alta con nombre de usuario, email, contraseña inicial y
   rol; asócielas al equipo que corresponda. → [Personas y equipos](usuarios.md)
3. **Revise qué modelo está disponible.** Compruebe en la tabla de modelos activos cuál
   servirá las consultas y si necesita añadir alguno más del catálogo.
   → [Modelos de IA](modelos.md)
4. **Asigne presupuestos.** Fije un límite de consumo por equipo y, si lo necesita, otro
   individual: se comprueban ambos a la vez. → [Presupuestos y límites](presupuestos.md)
5. **Pruebe en el Playground.** Lance una consulta que incluya datos personales
   ficticios y verifique en **Firewall en vivo** que el texto salió enmascarado hacia el
   modelo. → [Consultar la auditoría](auditoria.md)

Cuando emita credenciales para que una aplicación o herramienta se conecte a la pasarela,
continúe por [Llaves de acceso](llaves.md).

!!! note "¿Algo no responde?"
    Si acaba de añadir un modelo y no contesta pasados unos minutos, o si una pantalla no
    se comporta como se describe aquí, escriba a **soporte@basa-dev.com**.
