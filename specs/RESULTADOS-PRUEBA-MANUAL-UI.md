# Resultados de la prueba manual por UI — specs 043 / 044

**Fecha:** 10-sep-2026
**Entorno:** stack local ya levantado — Panel Eleia Guardian `http://localhost:8090`, Eleia Hub `http://localhost:8095`
**Navegador:** Chrome real (Claude in Chrome). Se empezó con el Browser pane pero quedó inutilizable a mitad de camino (fallo de la herramienta, no de la app) y se migró a Chrome.
**Método:** clicks reales en la UI. Donde no se pudo clickear por un desajuste de coordenadas de la herramienta de automatización, se usó `.click()` sobre el botón real del DOM (mismo handler) y queda aclarado en el paso.

**Credenciales creadas en esta prueba (paso 2):**
- usuario: `tomas.prueba`
- contraseña: `EleiaPrueba2026!`
- email: `tomas.prueba@elea-test.com`

**Cambios que quedaron en el entorno:** espacio `RRHH Aislamiento` con `empleado-prueba.txt`; usuario `tomas.prueba` (miembro de ese espacio, presupuesto $5/mes); `ana` quedó **desactivada** y con email cambiado a `ana.editada@elea-test.com` (resultado esperado de los pasos 10 y 11).

---

## P1 — "La memoria de chats es compartida"

### Paso 1 — Espacio nuevo + documento + pregunta 🟢

Creé el espacio **"RRHH Aislamiento"** desde el Hub (botón `+ Nuevo`). Subí `empleado-prueba.txt`, un .txt con PII deliberada (nombre, DNI 28.455.910, email, teléfono, legajo EL-7742, sueldo 2.450.000 ARS, sucursal Planta Los Polvorines).

**Qué vi:** al terminar la subida apareció un modal **`"empleado-prueba.txt" protegido`** con el conteo de entidades detectadas:

```
PHONE_NUMBER    1
EMAIL_ADDRESS   1
LOCATION        1
DNI             1
PERSON          1
```

El panel derecho pasó a `1 archivo` y listó `empleado-prueba.txt — 30 palabras`. El enmascarado corrió.

Pregunté (chip "Analizar documentos reales"): *"¿Podrías decirme qué hay en los documentos que subí?"*. Respuesta:

> En el documento que subiste, se encuentra la ficha de un empleado de Laboratorios Elea. Los detalles incluyen su nombre completo, DNI, dirección de correo electrónico, número de teléfono, legajo, puesto, sueldo bruto mensual, fecha de ingreso y sucursal. Sin embargo, los datos personales están protegidos y se presentan como tokens. Si necesitas información específica, por favor indícame.
>
> Fuente (RAG): empleado-prueba.txt · Respondió: azure-gpt-4o-mini

RAG recuperó bien y citó la fuente. El enmascarado se sostuvo en la respuesta.

⚠️ Dos cosas de este paso van como bugs aparte: las etiquetas de PII salen crudas de Presidio en inglés (bug #12), y el botón Enviar del chat estaba muerto (bug #5 — por eso usé el chip).

### Paso 2 — Alta de usuario cliente 🟢

Panel → Usuarios & Presupuestos → Usuarios & Equipos → `Registrar Miembro`. Cargué usuario, email, contraseña y rol **"Especialista"**. Se creó y apareció en la tabla al instante.

⚠️ La tabla lo muestra con rol **"Cliente"**, no "Especialista". Por API el usuario quedó `role: "client"`, `display_label: "clinician"`. El combo de alta no ofrece "Cliente" pero el de edición sí (bug #20).

### Paso 3 — El usuario nuevo NO ve el espacio de admin 🟢

Entré al Hub como `tomas.prueba` en una sesión limpia (Chrome no tenía cookie del Hub; equivale a incógnito).

**Qué vi — exactamente lo esperado:**

> Todavía no tenés espacios. Creá uno o pedile a tu administrador que te agregue.

No aparece ni "Contabilidad" ni "RRHH Aislamiento". Confirmado también por API: `/api/user/current` con su cookie devuelve `workspaces: []`.

*(Nota de rigor: a mitad del paso el Hub abrió ya logueado como admin en Chrome. Verifiqué con `curl` sin cookies → `{"isAuthenticated":false}`. Era la cookie de admin de sesiones previas del usuario, no una sesión global. **No hay bug ahí.**)*

### Paso 4 — Agregarlo como miembro 🟢

Desde admin: espacio → `Miembros` → escribí `tomas.prueba` → `Agregar`. Quedó listado como **`tomas.prueba (miembro)`** junto a `admin (dueño)`, con acciones "Hacer dueño" y "✕".

Recargué como `tomas.prueba`: ahora **sí ve "RRHH Aislamiento"** en su sidebar, con el documento y `1 archivo`. La membresía funciona.

### Paso 5 — Los hilos NO se mezclan 🔴 **FALLA — el reclamo de Tomás es real**

Al entrar `tomas.prueba` al espacio recién compartido, el Hub le abre el **"Hilo principal del espacio"** y le muestra **la conversación completa de admin**, que él nunca escribió:

> **U** — ¿Podrías decirme qué hay en los documentos que subí?
> **AI** — En el documento que subiste, se encuentra la ficha de un empleado de Laboratorios Elea […]
> Fuente (RAG): empleado-prueba.txt · Respondió: azure-gpt-4o-mini

**Descarté que fuera DOM residual del logout.** Recargué la página con `F5` (chat vacío, ningún espacio seleccionado), luego cliqueé el espacio: **los mensajes de admin volvieron desde el servidor**. Y directo contra la API, con la cookie de `tomas.prueba`:

```json
{ "sesion": "tomas.prueba", "rol": "client",
  "mensajes": [
    { "role": "user",      "txt": "¿Podrías decirme qué hay en los documentos que subí?" },
    { "role": "assistant", "txt": "En el documento que subiste, se encuentra la ficha de un empleado de L…" } ] }
```

`GET /api/workspaces/rrhh-aislamiento/messages` devuelve los mensajes de admin a otro usuario. **Es backend, no UI.**

Esto contradice el diseño documentado en el propio repo — `backend/src/models/workspace.py:88`:
> `# NULL = hilo principal de esa persona en ese espacio (uno por (workspace, usuario)).`

El hilo principal debería ser **uno por (espacio, usuario)** y en la práctica es **uno por espacio**.

**Lo que sí funciona:** creé un hilo propio con `tomas.prueba` y pregunté algo distinto ("¿En qué sucursal trabaja la persona de la ficha y cuál es su sueldo bruto mensual?" → *"Planta Los Polvorines… 2.450.000 ARS"*, RAG correcto). Volví como admin: **no** ve el contenido de ese hilo — el backend responde `{"error":"Ese hilo no te pertenece."}`.

**Resumen del alcance del bug:** el aislamiento de **hilos creados explícitamente** funciona. El que se filtra es **el hilo por defecto**, que es justo el que usa cualquiera que entra sin crear nada — o sea, el caso normal. Por eso Tomás lo ve como "la memoria es compartida".

---

## P3 — Cuentas de servicio

### Paso 6 — Costos → Top modelos 🟢

`gpt-4o-mini`, `azure-gpt-5.1-chat`, `azure-gpt-4o-mini`. **No aparece `license` ni `chat-ui`.** El fix se sostiene acá.

### Paso 7 — Tabla principal de usuarios 🔴 **FALLA**

La tabla "Miembros / Usuarios" **sí muestra** tres cuentas de servicio, como usuarios normales de rol "Cliente", con el juego completo de acciones (Asignar equipo · Restablecer contraseña · Editar · Desactivar · Dar de baja):

```
svc.anythingllm-provider    svc.anythingllm-provider@elea-internal.com    Cliente  …  Activo
svc.rag-masking             svc.rag-masking@elea-internal.com             Cliente  …  Activo
svc.anythingllm-provider2   svc.anythingllm-provider2@elea-internal.com   Cliente  …  Activo
```

No son de solo lectura: se pueden editar, desactivar y dar de baja desde el panel.

### Paso 8 — Sección "Cuentas de servicio" 🟡 **El mecanismo anda; los datos no**

La sección existe, arranca plegada, se despliega con "Mostrar" y es **de solo lectura** (columnas NOMBRE / PROPÓSITO / ESTADO, sin acciones). El texto explicativo está bien redactado.

Pero dice **"Cuentas de servicio (1)"** y contiene una sola fila:

```
svc.test-verificacion    Cuenta de servicio interna.    Activa
```

`svc.test-verificacion` es la cuenta creada en la prueba por API de la sesión anterior. **Las tres cuentas de servicio reales nunca fueron marcadas como tales.** El filtro no es por prefijo `svc.` sino por un flag que sólo se setea al crear: las cuentas preexistentes quedaron sin migrar.

**Contaminación relacionada, en otras dos pantallas:**
- **Costos → "Gasto por usuario"**: `svc.anythingllm-provider2 — $0.0005 — 1 petición`, listada como si fuera una persona.
- **Presupuestos → "Asignar Límite" → "O usuario individual"**: el combo lista las tres cuentas `svc.`; se les puede asignar presupuesto.

---

## Branding

### Paso 9 — Panel y Hub 🟡 **Bien al final, con un flash del branding viejo**

**Panel (`:8090`):** logo real de **EleIA** (wordmark con el punteado turquesa) en el login y en la sidebar. **No** hay ícono genérico de escudo. Título de pestaña: `Eleia Guardian`. Login: "Panel de administración de Eleia".

**Hub (`:8095`):** mismo logo real de EleIA en login, header y estado vacío del chat. Título de pestaña: `Eleia Hub`. Tenant: "Laboratorios ELEA".

**Lo que falla:** el HTML del Hub trae el branding viejo hardcodeado y lo pisa recién en runtime (`applyBranding()` contra `/api/branding`). Verificado en `client/public/index.html`:

```
11:   <title>Guardian Hub</title>
404:  <img src="/guardian-logo.svg" … id="login-logo">
429:  <img src="/guardian-logo.svg" … id="navbar-logo">
755:  let hubBrand = { name: 'Guardian Hub', … logoUrl: '/guardian-logo.svg', governanceLabel: 'Guardian' };
```

**Lo vi en vivo:** el título de la pestaña arrancó como **"Guardian Hub"** y recién después cambió a "Eleia Hub", y la red muestra `GET /guardian-logo.svg → 200` antes de `GET /eleia-logo.png`. Con red lenta o si `/api/branding` falla, el cliente ve el branding genérico.

Además: la cuenta admin tiene email **`admin@sentinel.com.ar`** — nomenclatura del cliente anterior, visible en la tabla de usuarios.

---

## P5 — Ciclo de vida de usuario

### Paso 10 — Editar SOLO el email 🟢

Edité `ana`: `ana.nueva@elea-test.com` → `ana.editada@elea-test.com`, sin tocar el rol. Después de guardar:

```
ana   ana.editada@elea-test.com   Cliente   Sin Equipo   sin dato   Activo
```

Rol, equipo y estado intactos. El modal sólo expone EMAIL y ROL, así que no hay riesgo de pisar otros campos.

### Paso 11 — Desactivar a otro usuario 🔴 **No pide ninguna confirmación**

Cliqueé "Desactivar" en la fila de `ana`. **Se desactivó de inmediato, sin modal, sin `confirm()`, sin deshacer.** Un solo click.

El resultado sí es correcto: la fila quedó `… Desactivado` y el botón cambió a "Reactivar".

Confirmado en el código — `frontend/src/pages/UsersPage.tsx:568`:

```js
const handleToggleActive = async (u: User) => {
  try {
    await api.patchUser(u.id, { is_active: !u.is_active });
    await fetchData();
  } catch (err: any) { alert(err?.message || "No se pudo cambiar el estado del usuario."); }
};
```

Va directo a la API. Contrasta con "Dar de baja", que sí tiene modal con confirmación por tipeo del username.

### Paso 12 — Autodesactivarme 🔴 **La UI sí manda el request**

Limpié el registro de red, cliqueé "Desactivar" en mi propia fila (`admin`) y miré la pestaña Network:

```
PATCH http://localhost:8090/api/v1/users/d11a67a6-5484-4a08-87e5-048c755bfa95  →  409
```

**Hubo request.** El pedido salió con mi propio id y lo frenó el backend, no la UI. El paso pedía que la UI lo impidiera *antes* de llamar.

**Resultado final seguro:** `admin` sigue `Activo`. El backend tiene la guarda en `_bloquear_baja_insegura()` (`backend/src/api/users.py`), que devuelve 409 `"No podés darte de baja a vos mismo."` — y el comentario del código documenta que esta guarda se agregó justo por este bug el 09-sep.

**Dos problemas igual:**
1. `handleToggleActive` no repite la validación de UI que sí hace `handleConfirmBaja` ("No podés darte de baja a vos mismo"). El toggle depende enteramente del 409.
2. El error se muestra con **`alert()` nativo del navegador**, no con la UI del panel — inconsistente con el resto, que usa modales y mensajes en línea.

---

## Exploración libre (paso 13)

**Consola del navegador:** limpia en ambas apps. Ningún error ni warning. Sólo mensajes de Vite y React DevTools.
⚠️ Eso mismo delata que **el panel corre en modo desarrollo de Vite** (`@vite/client`, HMR), no con un build de producción.

**Seguridad y Guardianes** 🟢 — la mejor pantalla del panel. Textos en español claros, distingue bien "Aplicándose" / "No disponible" / "Próximamente · no instalado", y explica por qué las capas base no tienen interruptor. Único roce: el anglicismo "(Secret Detection)" en un título.

**Gobernanza** 🔴 — entre capas con nombre humano ("Enmascarado de datos personales", "Bloqueo de secretos") aparece el identificador crudo **`enforcement_tier_estricto`**, en snake_case y a medio traducir.

**Políticas de Cumplimiento** 🟢 — completa y coherente. Detalle menor: en "Distribución por propósito de tratamiento" figura `coding-assistant` sin traducir. Mucha sigla sin glosario (DPO, DPA, DPIA, DSR, DSAR, RAT, PHI), aunque es jerga legítima del dominio.

**Modelos & Ollama** 🔴 — tres problemas:
1. El menú dice **"Modelos & Ollama"** pero el título de la página es "Modelos de IA & Proveedores". Además **no hay ningún modelo Ollama configurado** (los tres son AZURE OPENAI): el menú nombra un producto de terceros que ni se usa.
2. Error técnico crudo en pantalla: *"Estado del motor no disponible: **status.json** no existe todavía: el **volumen** del motor puede no estar montado en este entorno, o el **supervisor** no arrancó."*
3. **Contradicción riesgosa en el ruteo semántico:** la ruta #3 se muestra como `LOCAL · Conversación trivial · (modelo local, coste 0)` pero apunta a **`azure-gpt-4o-mini`**, que es Azure en la nube y con costo ($0.17 IN / $0.66 OUT). En una pantalla de gobernanza, decirle a un cliente "local, coste 0" sobre un modelo que sale a la nube es un problema de confianza, no cosmético.

**Logs de Auditoría** 🔴 — la columna MODELO muestra `license`, `auth` y `servicio` como si fueran modelos (`license` aparece 8 veces en la primera página). **Es el mismo P3 que ya se limpió en Costos, pero acá sigue.**

**Espacios sin asignar** 🟢 — vacío, con texto correcto y mención a "Eleia Hub".

**Hub — selector de modelo** 🟢 — elegí `azure-gpt-5.1-chat` y pregunté en chat directo. Respondió y el pie confirma **"Respondió: azure-gpt-5.1-chat"**. El selector se respeta.
*(Observación de producto: el modelo se presenta como "Soy ChatGPT, un modelo de lenguaje de OpenAI basado en GPT‑5.5" — en un producto white-label de Eleia no hay system prompt de marca que lo cubra.)*

**Hub — presupuesto** 🟢 — asigné $5 mensuales a `tomas.prueba` desde Presupuestos y el Hub lo refleja al instante: badge verde **`$0.00 / $5.00`** bajo su nombre, reemplazando "Sin presupuesto asignado". La cascada funciona.
⚠️ En el panel el período se muestra como **`MONTHLY`**, en inglés y mayúsculas, en una UI en español.

**Atribución de costos (chat directo)** 🟢 — confirmado como decía la nota de alcance: el chat directo atribuye bien. Después de mi pregunta, Costos → "Gasto por usuario" muestra `admin — $0.0003 — 6 peticiones`. (El caso RAG queda fuera de alcance, no se reporta.)

**Otros detalles del Hub:**
- Nombres técnicos a la vista del cliente: **"Data Ingest Core"** (en inglés, en UI española), **"LanceDB Local"** (nombre de la librería de vector store), y el rol crudo en el header: **"tomas.prueba · client"**, **"admin · tenant_admin"**.
- **"Eleia GuardIAn"** con esa capitalización en el panel "Motor RAG Activo" — inconsistente con "Eleia Guardian" del resto.
- Un usuario que es **solo miembro** (no dueño) ve igual los botones **"Ajustes del espacio"** y **"Eliminar espacio"** (este último en rojo). Peor: esos tres botones aparecen incluso **sin ningún espacio**, en el estado vacío de un usuario recién creado.
- El botón dice **"Subir archivos"** (plural) pero el `<input type="file">` no es `multiple`: sube de a uno.
- Formato de hora inconsistente dentro de la misma app: `06:07 PM` en el hilo principal vs `20:18` en el hilo nuevo.

---

## 🔴 Bugs encontrados

| # | Severidad | Bug | Dónde |
|---|---|---|---|
| 1 | **Crítica** | **El "Hilo principal del espacio" es compartido entre todos los miembros.** Un usuario recién agregado ve la conversación completa de otro. Confirmado por API con su propia cookie, tras recarga limpia. Contradice el diseño documentado (`models/workspace.py:88`: uno por espacio+usuario). **Es el reclamo de Tomás.** | Backend — `GET /api/workspaces/{slug}/messages` |
| 2 | **Alta** | **Las 3 cuentas de servicio reales aparecen en la tabla principal de usuarios** como "Cliente" editable/desactivable. La sección "Cuentas de servicio" sólo contiene `svc.test-verificacion` (la de prueba). El flag sólo se setea al crear; las preexistentes no se migraron. | Panel → Usuarios & Equipos |
| 3 | Alta | **Autodesactivación: la UI manda el request** (`PATCH … → 409`). Sólo el backend lo frena. `handleToggleActive` no repite la validación que sí hace `handleConfirmBaja`. Además el error se muestra con `alert()` nativo. | `UsersPage.tsx:568` |
| 4 | Alta | **"Desactivar" no pide ninguna confirmación.** Un click y el usuario queda desactivado, sin modal ni deshacer. | `UsersPage.tsx:568` |
| 5 | Alta | **El botón "Enviar" del chat queda muerto sin ningún feedback.** `.toast-msg` es `position:fixed; bottom:20px; right:20px; opacity:0; z-index:999` **sin `pointer-events:none`**, y su ancho depende del texto del último toast. Con un toast largo (ej. el de subida de archivo) tapa el botón e intercepta los clicks para siempre. Verificado: `document.elementFromPoint()` sobre el botón devuelve `DIV#toast-notification`. | `client/public/index.html:389` |
| 6 | Media | **Logs de Auditoría muestran `license`, `auth` y `servicio` como modelos.** El fix de P3 se aplicó a Costos pero no a esta pantalla. | Panel → Logs de Auditoría |
| 7 | Media | **Cuentas `svc.` contaminan otras dos pantallas:** `svc.anythingllm-provider2` en Costos → "Gasto por usuario", y las tres en el combo de "Asignar Límite". | Costos / Presupuestos |
| 8 | Media | **Ruta de ruteo etiquetada "LOCAL · modelo local, coste 0" apunta a `azure-gpt-4o-mini`** (Azure, en la nube, con costo). Contradicción grave en una pantalla de gobernanza. | Panel → Modelos |
| 9 | Media | **Error técnico crudo en pantalla:** "…`status.json` no existe todavía: el **volumen** del motor puede no estar montado…, o el **supervisor** no arrancó." | Panel → Modelos |
| 10 | Media | **`handleLogout()` no limpia el DOM.** Limpia las variables JS pero no re-renderiza: el siguiente usuario que entra en la misma pestaña ve en pantalla los mensajes y documentos del anterior hasta recargar. Distinto del bug #1, pero suma a la misma percepción. | `index.html` (handleLogout) |
| 11 | Media | **Un miembro no-dueño ve "Eliminar espacio" y "Ajustes del espacio".** Y esos botones aparecen incluso sin ningún espacio (estado vacío de un usuario nuevo). | Hub — sidebar |
| 12 | Media | **Nombres técnicos filtrados a la UI del cliente:** `enforcement_tier_estricto` (Gobernanza); "Modelos & **Ollama**" en el menú (sin ningún modelo Ollama configurado); `LanceDB Local` y `Data Ingest Core` (Hub); roles crudos `client` / `tenant_admin` en el header del Hub; etiquetas de Presidio en inglés (`PHONE_NUMBER`, `EMAIL_ADDRESS`, `LOCATION`, `PERSON`) en el modal de protección; `coding-assistant` (Compliance); `MONTHLY` (Presupuestos). | Varias |
| 13 | Baja | **El título del hilo se descarta.** Escribí "Hilo privado de Tomas" y se creó como **"Hilo edf1c771"** (un id truncado). | Hub → + Hilo |
| 14 | Baja | **La lista de hilos muestra hilos de otros usuarios.** Admin ve "Hilo edf1c771" (de Tomás); al abrirlo muestra un chat vacío en vez del error real del backend (`"Ese hilo no te pertenece."`). Fuga de metadatos + confuso. | Hub — sidebar |
| 15 | Baja | **"Elegí un espacio primero" con el espacio claramente seleccionado.** Tras loguearse sin recargar, `currentWorkspace` queda `null` aunque la vista muestra el espacio, sus documentos y su hilo. | Hub → + Hilo |
| 16 | Baja | **Flash del branding viejo en el Hub:** `<title>Guardian Hub</title>` y `/guardian-logo.svg` hardcodeados en el HTML; Eleia se aplica recién en runtime. Vi el título "Guardian Hub" antes de "Eleia Hub". Si `/api/branding` falla, el cliente ve el branding genérico. | `client/public/index.html:11,404,429,755` |
| 17 | Baja | **`admin@sentinel.com.ar`** — email con la nomenclatura del cliente anterior, visible en la tabla de usuarios. | Panel → Usuarios |
| 18 | Baja | **El rol elegido en el alta no es el que se muestra.** Elegí "Especialista" y la tabla muestra "Cliente" (`role: client`, `display_label: clinician`). El combo de alta no ofrece "Cliente"; el de edición sí. | Panel → Registrar Miembro |
| 19 | Baja | **El panel corre en modo desarrollo de Vite** (`@vite/client`, HMR, React DevTools), no con build de producción. | `:8090` |
| 20 | Cosmético | Formato de hora inconsistente (`06:07 PM` vs `20:18`); "Subir archivos" en plural sobre un input que no es `multiple`; "Eleia GuardIAn" con capitalización distinta al resto. | Hub |

## 🟢 Todo OK

- **Paso 1** — Subida de documento, detección y enmascarado de PII (5 tipos), RAG conversacional con cita de fuente y modelo usado.
- **Paso 2** — Alta de usuario cliente desde el panel.
- **Paso 3** — **Aislamiento de espacios: correcto.** El usuario nuevo ve el estado vacío ("Todavía no tenés espacios…") y por API `workspaces: []`. No se filtra ningún espacio de admin.
- **Paso 4** — Alta de miembro desde "Miembros"; el espacio aparece para el usuario agregado.
- **Paso 5 (parcial)** — **Los hilos creados explícitamente sí están aislados:** admin no puede leer el hilo de Tomás; el backend responde `"Ese hilo no te pertenece."` Lo que falla es sólo el hilo por defecto (bug #1).
- **Paso 6** — Costos → Top modelos limpio: **sin `license` ni `chat-ui`**.
- **Paso 8** — La sección "Cuentas de servicio" existe, arranca plegada, se despliega y es de solo lectura, con buen texto explicativo. El mecanismo está bien; le faltan los datos (bug #2).
- **Paso 9** — Logo real de Eleia en panel y Hub, en login y navegación. Nada de ícono genérico tipo escudo. Títulos de pestaña "Eleia Guardian" / "Eleia Hub".
- **Paso 10** — Editar sólo el email no toca rol, equipo ni estado.
- **Paso 11 (parcial)** — La desactivación se aplica bien y queda el badge "Desactivado" con botón "Reactivar".
- **Paso 12 (resultado)** — **Nadie se autodesactiva:** el backend devuelve 409 y `admin` sigue Activo. La protección de fondo está.
- **Paso 13** — Consola del navegador sin un solo error ni warning en ambas apps. Selector de modelo del Hub respetado. Presupuesto en cascada visible en el Hub (`$0.00 / $5.00`). Chat directo atribuye el costo al usuario real. Seguridad y Guardianes y Políticas de Cumplimiento bien redactadas y coherentes.

---

## Fuera de alcance (no reportado como bug nuevo)

- Preguntas tabulares / cruces entre CSV-Excel — motor de chunks semánticos, ya trackeado en spec 046.
- Atribución del costo de preguntas RAG dentro de un espacio al usuario real — limitación arquitectónica ya aceptada. (El chat **directo** sí atribuye bien; verificado arriba.)

## Lo prioritario

**El bug #1 es el que hay que arreglar antes de volver a hablar con Tomás.** Es literalmente su reclamo, es de backend, y el arreglo está acotado: el hilo por defecto debe resolverse por `(workspace, usuario)` como ya dice el comentario del modelo, en vez de por `workspace` solo. Los bugs #2 y #6 son el P3 a medio cerrar: el mecanismo de UI ya está, falta migrar el flag de las cuentas preexistentes y aplicar el mismo filtro en Logs de Auditoría.
