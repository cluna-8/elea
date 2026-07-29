# Hechos verificados en vivo (29-jul-2026, bundle :piloto, instancia demo 0km)

NO es contenido del sitio — es el brief de redacción. Todo lo de abajo fue observado
en la UI real o verificado por API. No inventar nada que no esté aquí o en las fuentes citadas.

## Producto (como lo ve el cliente)

- Título de la instalación: **Cámara de Comercio — AI Gateway** (brand pack del bundle).
  Tagline: "Uso seguro y auditado de IA". Soporte: soporte@basa-dev.com.
- Login: campos Usuario / Contraseña, botón **"Ingresar al Panel"**.
- El PRIMER login de `admin` en una instalación nueva CREA al admin con la contraseña
  que se escriba (mínimo 12 caracteres). No hay contraseña de fábrica. Los logins
  siguientes son login normal. Cada usuario puede cambiar su propia contraseña
  (botón **"Cambiar mi contraseña"** abajo a la izquierda); el admin puede
  **"Restablecer contraseña"** de cualquier usuario desde la tabla de miembros.

## Menú lateral del panel de administración (rol Administrador)

Panel Principal · Playground · Firewall en vivo · Modelos & Ollama · Costos ·
Usuarios & Presupuestos · Gobernanza · Seguridad y Guardianes ·
Políticas de Cumplimiento · Logs de Auditoría · Documentación

## Página "Usuarios & Presupuestos" (título en pantalla: "Administración")

Pestañas: Resumen · Usuarios & Equipos · Llaves Virtuales · Presupuestos · Autenticación & SSO.

- **Equipos**: botón "Nuevo Equipo" → modal "Crear Nuevo Equipo" (Nombre del Equipo,
  Descripción, botón Crear). Los equipos tienen Base Legal, Riesgo AI Act, Proyecto
  Compliance y Consumo.
- **Usuarios**: botón "Registrar Miembro" → modal con: Nombre de Usuario, Email,
  Contraseña de acceso (mín. 12 caracteres, "Entréguesela a la persona por un canal
  seguro"), Rol (Especialista / Investigador / Desarrollador / Administrador),
  Asociar a Equipo (opcional), y perfil de compliance individual opcional
  (Base legal GDPR, Nivel de riesgo AI Act, Proyecto de compliance — por defecto
  "Heredar del equipo").
- **Llaves Virtuales** ("Bearer Tokens"): botón "Generar Llave Virtual" → modal con:
  Nombre de la Llave, Equipo O Usuario, Presupuesto Máx. (USD), Período de Reinicio
  (Diario/Semanal/Mensual/Anual), Límite RPM (default 60), Límite TPM (default 100000),
  Proyecto de compliance opcional. Al generar aparece modal
  **"¡Llave Virtual Generada!"**: "Copie la clave ahora. Por motivos de seguridad, no se
  volverá a mostrar." La llave tiene formato `sk-basa-...`. En la tabla queda solo el
  preview (`sk-...XXXX`), con acciones Revocar.
- **Presupuestos**: "Límites de Consumo" — botón "Asignar Límite" → modal: Equipo o
  Usuario Individual, Límite Máximo (USD), Límite Máximo (Tokens), Período de Reinicio.
  "Doble capa activa: se verifican ambos (personal + equipo) simultáneamente."

## Página "Modelos & Ollama" (título: "Modelos de IA & Proveedores")

- Tabla "Modelos Activos en la Pasarela": Nombre, Proveedor, Compliance
  (p.ej. "UE Compliant"), Precio / 1M tokens, Fallback automático (combobox), Eliminar.
- En el piloto viene preconfigurado `camara-comercio-local` (modelo local, gratis,
  UE Compliant — corre en los propios servidores, los datos no salen).
- Botón "+ Agregar Modelo" → modal "Catálogo de Modelos" con filtros:
  Todos / Solo UE Compliant / Local (Ollama) / + Modelo personalizado.
  "Los modelos marcados UE Compliant soportan residencia de datos en Europa."
- GOTCHA verificado en el ensayo del piloto: tras dar de alta un modelo nuevo el motor
  puede tardar/necesitar un reinicio del servicio para servirlo. Redactar como: si el
  modelo nuevo no responde a los pocos minutos, contacte a su soporte técnico
  (soporte@basa-dev.com). NO dar instrucciones de docker al cliente.

## Playground (título: "Playground Seguro")

- Selector de modelo arriba a la derecha; caja "Escriba un mensaje…" y botón Enviar.
- Panel derecho: "Capas de Seguridad" (01 Enmascaramiento PHI/PII, 02 Optimización de
  Contexto, 03 Políticas de Cumplimiento, 04 Canal de Enrutamiento LLM, 05 Restauración
  y Desenmascaramiento) y "Debugger Técnico" con Métricas de Transacción (modelo,
  latencia, costo, tokens) y JSON de petición/respuesta.
- Verificado en vivo: prompt con nombre + DNI + teléfono → la respuesta vuelve con los
  datos originales (se restauran localmente), y en "Firewall en vivo" se ve el prompt
  que salió hacia el modelo ENMASCARADO: `[PERSON_0]`, `[ES_NIF_0]`, `[PHONE_NUMBER_0]`,
  `[LOCATION_0_…]`. Con el modelo local la latencia observada fue ~40 s (hardware demo).

## Firewall en vivo

- Contadores: peticiones / permitidas / bloqueadas. Cada evento muestra estado
  (PERMITIDO/BLOQUEADO), origen, modelo, hora, "PII enmascarada: N× TIPO" y el texto
  enmascarado que salió. Aviso en pantalla: las capas aplicadas se ven por evento y la
  configuración vigente está en **Gobernanza**.
- El texto de auditoría NO guarda prompts en claro ("Auditado sin texto de prompt ni
  PII cruda" — cabecera de la página).

## Portal del usuario final (rol no-admin, p.ej. Especialista)

- Al entrar ve el **"Asistente Seguro"**: "Sus consultas se procesan con protección de
  datos activa". Selector de modelo, chat simple.
- Cada respuesta muestra: modelo usado, costo, y **"N datos personales protegidos"**.
- Verificado: consulta con nombre y DNI → 2 datos protegidos, respuesta útil.
- Pie: "Respuestas generadas por IA — verifique la información importante antes de
  aplicarla."

## API para conectar herramientas (verificado por curl contra la instancia)

- Endpoint chat: `POST <URL-de-su-instalación>/api/v1/chat/completions`
  con `Authorization: Bearer sk-basa-...` (llave virtual) y body JSON:
  `{"message": "…", "model": "camara-comercio-local"}`.
  La respuesta incluye `response` y `pipeline_metadata` (capas aplicadas, PII
  enmascarada, costo). El campo es `message` (string), NO `messages` estilo OpenAI.
- Para herramientas de programación tipo Claude Code existe la superficie
  `/api/v1/gw/v1/messages` (passthrough con la sesión propia de la herramienta).
  Documentarla solo como mención breve "consulte a su administrador"; el detalle
  técnico vive en la documentación de producto, no en esta guía.

## Extensión del navegador

- El instalador de la Cámara incluye `extension-camara-comercio.zip` (nombre de la
  extensión: cc-guardian). Protege datos personales escritos en asistentes de IA web
  (p.ej. ChatGPT, Claude) enmascarándolos antes de que salgan del navegador; la
  organización define qué se enmascara y registra el uso.
- NO hay screenshots de la extensión en esta tanda. Guía corta y textual; la instala/
  distribuye el administrador.

## Screenshots disponibles (docs/assets/screenshots/)

- 01-login.png — pantalla de login
- 02-panel-principal.png — Panel Principal con métricas (peticiones, costo, incidentes
  PII, bloqueos), Top Modelos, Estado del Sistema, Activaciones de Guardianes
- 10-modelos-lista.png — Modelos activos en la pasarela
- 11-modelos-catalogo.png — modal Catálogo de Modelos
- 20-equipo-nuevo.png — modal Crear Nuevo Equipo (relleno: "Comercio Exterior")
- 21-alta-usuario.png — modal Registrar Miembro (relleno: lucia.perez)
- 22-usuarios-tabla.png — tabla Equipos + Miembros
- 30-llave-nueva.png — modal Generar Llave Virtual (relleno)
- 31-llave-generada.png — modal "¡Llave Virtual Generada!" con la llave visible
- 32-llaves-tabla.png — tabla de llaves activas
- 33-presupuesto-asignar.png — modal Asignar Límite / Presupuesto
- 34-presupuestos-lista.png — Límites de Consumo con presupuesto creado
- 40-playground-chat.png — Playground con pregunta y respuesta
- 41-firewall-vivo.png — Firewall en vivo con el prompt ENMASCARADO ([PERSON_0]…)
- 50-auditoria.png — Logs de Auditoría
- 51-guardianes.png — Seguridad y Guardianes
- 52-politicas.png — Políticas de Cumplimiento
- 53-gobernanza.png — Gobernanza
- 54-costos.png — Costos
- 60-portal-usuario.png — portal Asistente Seguro (vacío)
- 61-portal-respuesta.png — portal con respuesta y "2 datos personales protegidos"

## Datos de demo usados (TODOS ficticios — mantener coherencia si se citan)

Equipo "Comercio Exterior"; usuarios lucia.perez (lucia.perez@ejemplo.es, Especialista)
y marcos.gil (marcos.gil@ejemplo.es); llave "llave-lucia-perez" ($20/mes);
presupuesto de equipo $100/mes. DNI 12345678Z y teléfono 612 345 678 son ficticios.

## Reglas de redacción (OBLIGATORIAS)

1. Idioma: español neutro profesional (tratamiento de "usted").
2. Guías orientadas a TAREA: título = qué logra el lector; pasos numerados; una captura
   por paso clave con `![texto alt](../assets/screenshots/XX.png)` (ruta relativa desde
   la página). Admonitions de mkdocs-material (`!!! note`, `!!! warning`) con moderación.
3. PROHIBIDO mencionar: litellm, berriai, presidio (nombres del motor — gate de release);
   precios/costes internos del fabricante, licencias, distribución, roadmap, specs,
   números de issue/PR, nombres del equipo de desarrollo, "piloto", "demo", "PoC".
4. No documentar nada que no esté en este brief o visible en las capturas. Si una
   sección necesitaría algo no verificado, escribir menos, no inventar.
5. No incluir contraseñas en texto (las de este brief son solo contexto).
6. El lector admin NO tiene acceso a servidores: nunca instrucciones de docker/terminal,
   salvo el bloque curl del endpoint de chat (que es para desarrolladores del cliente).
