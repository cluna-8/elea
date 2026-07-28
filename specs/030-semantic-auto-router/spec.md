# Feature Specification: Auto-router semántico + rediseño «Modelos & Ollama»

**Feature Branch**: `030-semantic-auto-router`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "Portar el auto-router semántico de llm-guardian y mejorar
«Modelos & Ollama» para alojarlo: switch on/off, timeout si hace falta, y pensar bien qué
pasa con N modelos de Ollama (¿a cuál va?). Agregar un par de modelos además de gpt-4o-mini
para probarlo bien. Fallback siempre a local por defecto (decisión JF 28-jul). Demo en la
sede el jueves 31-jul."

## Contexto y evidencia previa (28-jul)

- El servicio de llm-guardian (140 líneas: embeddings de utterances por ruta + coseno +
  umbral + best-of) **funciona con embeddings 100% locales**: benchmark con las rutas
  reales y 9 queries en español → `qwen3-embedding:0.6b` (Ollama, 639 MB) clasifica **8/9**
  (nomic-embed-text y granite-embedding 7/9; ambos fugan chitchat a premium). Script
  reproducible: `bench_embeddings.py` (portar a `specs/030-…/`).
- llm-guardian usaba Azure para embeddings → **inaceptable acá**: el contenido del prompt
  NO puede salir de la máquina para decidir el ruteo (Principio I + residencia).
- El único fallo restante del benchmark («hola, ¿qué tal?» → premium 0.55) se resuelve por
  diseño con una **tercera ruta "conversación trivial" → modelo local** (coste 0).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - «Auto» en el chat: cada consulta al modelo que corresponde (Priority: P1)

Un usuario del Playground (o del portal de usuario final) elige el modelo **«Auto»**. El
sistema clasifica semánticamente su consulta y la enruta: código/análisis/razonamiento →
modelo premium cloud; resumen/redacción/traducción → modelo económico cloud; conversación
trivial y todo lo que no matchea → **modelo local (coste 0)**. La decisión es visible y
explicable: el Debugger Técnico y «Conexiones en vivo» muestran ruta elegida, score y
modelo final (Principio VIII: datos reales, no cosmética).

**Why this priority**: es LA feature de la demo del jueves («cada pregunta al modelo justo,
lo barato a local, sin que el usuario piense») y el argumento de ahorro de costes del
producto. Sin panel ni switch ya es demostrable.

**Independent Test**: con 3 prompts (uno de código, uno de resumen, un saludo) el registro
muestra 3 modelos destino distintos; la batería de 9 queries del benchmark acierta ≥8.

**Acceptance Scenarios**:

1. **Given** el catálogo con premium+mini+local y el router activo, **When** un usuario
   manda «escribí una función en python…» con modelo «Auto», **Then** responde el modelo
   premium y el evento registra ruta=código, score y modelo real.
2. **Given** ídem, **When** manda «resumime este documento…», **Then** responde el modelo
   económico con su ruta registrada.
3. **Given** ídem, **When** manda «hola, ¿qué tal?» (o cualquier consulta bajo umbral),
   **Then** responde el modelo local a coste 0.
4. **Given** el modelo de embeddings caído, **When** un usuario usa «Auto», **Then** la
   consulta se sirve igual por el default local Y el evento registra que el ruteo degradó
   (nunca fallo silencioso).
5. **Given** una consulta con PII, **When** se rutea, **Then** el texto usado para embeber
   jamás sale de la máquina (embeddings locales) y el masking de la petición al modelo
   destino aplica igual que siempre.

---

### User Story 2 - Panel de ruteo en «Modelos & Ollama» con switch on/off (Priority: P2)

El admin gestiona el ruteo desde la página «Modelos & Ollama» rediseñada: un **switch
global on/off** (pedido explícito de JF), las rutas con sus utterances/umbral/modelo
destino (elegido del catálogo real — resuelve «¿y si hay N modelos de Ollama, a cuál
va?»: al que la ruta declare, y el **default configurable** apunta a UNO explícito),
timeout del ruteo, y el modelo de embeddings en uso con su estado (cargado/ausente).

**Why this priority**: sin esto el ruteo es un JSON a mano; con esto es una feature de
producto operable por el cliente. La demo puede mostrarlo aunque se edite poco.

**Independent Test**: apagar el switch → «Auto» sirve por el default sin llamar a
embeddings; editar el modelo destino de una ruta → la siguiente consulta va al nuevo
destino sin reiniciar nada (config caliente, como las ediciones de rutas en llm-guardian).

**Acceptance Scenarios**:

1. **Given** el switch OFF, **When** un usuario elige «Auto», **Then** la consulta va al
   default_model directo y NO se genera ninguna llamada de embeddings.
2. **Given** una ruta apuntando a un modelo que el admin elimina del catálogo, **Then** el
   panel lo señala (ruta rota) y el runtime cae al default — nunca 500.
3. **Given** una edición de utterances, **When** se guarda, **Then** aplica en la
   siguiente consulta (cache por hash de contenido, sin restart del motor).
4. **Given** un usuario sin rol admin, **Then** ve «Auto» como un modelo más y jamás el
   panel de configuración.

---

### User Story 3 - Fallback siempre-a-local + honestidad del modelo real (Priority: P3)

Todo modelo cloud del catálogo lleva **fallback automático al modelo local** por defecto
(decisión sellada de JF 28-jul: «que siempre vaya a local, sí»). Verificado en vivo el
28-jul: OpenAI caído → 200 en 11 s respondido por el local, y el campo `model` de la
respuesta dice el modelo REAL que contestó. La UI conserva esa honestidad: el badge del
modelo en la respuesta y el registro reflejan quién contestó de verdad, con señal visible
de «degradado por caída».

**Why this priority**: continuidad de servicio vendible («se cae el cloud y tu gente sigue
trabajando gratis en local») y coherente con la residencia. Ya casi funciona — falta
generalizarlo a todos los cloud del catálogo y la señal honesta en UI.

**Independent Test**: con el api_base de un cloud roto a propósito, una consulta a ese
modelo responde 200 desde el local y el evento registra la sustitución.

**Acceptance Scenarios**:

1. **Given** cualquier modelo cloud del catálogo caído, **When** un usuario lo consulta,
   **Then** responde el modelo local y el registro + UI muestran el modelo real y el motivo.
2. **Given** el alta de un modelo cloud nuevo por el panel, **Then** nace con fallback al
   local sin acción extra del admin (default, no opción escondida).
3. **Given** el modelo LOCAL caído, **Then** NO hay fallback local→cloud (violaría la
   residencia que motiva el modelo local — regla existente que se conserva): error honesto.

---

### Edge Cases

- Consulta larguísima → se embebe solo el prefijo (500 chars, como llm-guardian); registrar
  el truncado en el score no es necesario, el ruteo es best-effort declarado.
- Catálogo sin modelo local (cliente solo-cloud) → el default_model es el que el admin
  configure; el seed del piloto trae local como default.
- `auto_router.json` ausente/corrupto → default + evento de degradación (nunca 500).
- Timeout del embedding (config del panel, default 5 s) → default + evento de degradación.
- Dos rutas empatadas en score → gana la de mayor score absoluto; empate exacto → la
  primera declarada (determinista, documentado en el panel).
- Utterances editadas con el motor sirviendo tráfico → cache por hash: cero ventana de
  inconsistencia relevante (cada consulta usa la config leída en su momento).
- «Auto» pedido por la ruta /gw (coding tools byok): FUERA de alcance v1 (los coding tools
  declaran modelo explícito); si llega `model=auto` por /gw se responde el default local.
  Registrado como asunción y candidato a v2.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST ofrecer «Auto» como pseudo-modelo seleccionable en el chat
  (Playground y portal), visible como un modelo más para el usuario final.
- **FR-002**: El ruteo MUST clasificar por similitud semántica contra utterances por ruta
  (best-of, umbral por ruta) y elegir el modelo destino declarado por la ruta ganadora.
- **FR-003**: Los embeddings del ruteo MUST producirse en la máquina (modelo local vía el
  motor); el contenido de la consulta MUST NOT salir del host para decidir el ruteo.
- **FR-004**: Bajo umbral, fallo o timeout de embeddings, config ausente o switch OFF, el
  sistema MUST servir por el `default_model` configurado — degradación siempre funcional y
  SIEMPRE registrada (nunca silenciosa; gap de honestidad ya conocido en otros planos).
- **FR-005**: El admin MUST poder: activar/desactivar el ruteo global (switch), editar
  rutas (nombre, descripción, utterances, umbral, modelo destino del catálogo real),
  elegir `default_model`, y configurar el timeout — todo desde «Modelos & Ollama», con
  efecto sin reinicio del motor.
- **FR-006**: La decisión de ruteo (ruta, score, modelo final, degradado sí/no) MUST ser
  visible en el Debugger Técnico y en «Conexiones en vivo», y quedar en la auditoría
  durable como metadato de la transacción.
- **FR-007**: Todo modelo cloud MUST nacer con fallback al modelo local por defecto
  (aplicable a los existentes en la migración de seed); el fallback local→cloud MUST NOT
  existir. La respuesta MUST identificar el modelo que realmente contestó.
- **FR-008**: El seed del piloto MUST traer 3 rutas: código/análisis→premium,
  redacción/resumen→económico, conversación-trivial→local; `default_model`=local.
- **FR-009**: El coste mostrado MUST corresponder al modelo que contestó (local=0), nunca
  al solicitado (Principio V: coste honesto).
- **FR-010**: El masking/política MUST aplicar sobre la petición al modelo destino
  exactamente igual que si el usuario lo hubiera elegido a mano (el ruteo ocurre ANTES y
  aparte del pipeline de protección, sin cortocircuitarlo).

### Key Entities

- **Ruta semántica**: nombre, descripción, utterances de ejemplo, umbral, modelo destino
  (referencia al catálogo), orden declarado. Vive en la config caliente del router.
- **Config del router**: switch global, default_model, timeout, modelo de embeddings;
  editable por admin, versionable en la config del volumen (no en imagen).
- **Decisión de ruteo**: ruta ganadora, score, modelo final, flag degradado — viaja como
  metadato al debugger, la vitrina y la auditoría.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: La batería de 9 queries en español del benchmark acierta ≥8/9 contra el
  seed de rutas del piloto, ejecutada contra el stack levantado (no unit-mock).
- **SC-002**: Latencia añadida por el ruteo (p50) ≤ 1,5 s con el modelo de embeddings
  local en frío razonable; con cache de utterances caliente, ≤ 400 ms.
- **SC-003**: Con el switch OFF: cero llamadas a embeddings y «Auto» sirve por default
  (verificable en los logs del motor).
- **SC-004**: Demo de 3 prompts → 3 modelos destino distintos visibles en «Conexiones en
  vivo» con ruta y score, sin tocar nada entre prompts.
- **SC-005**: Con un cloud caído, consulta a ese modelo → 200 desde local en ≤ 15 s con
  el modelo real identificado en respuesta y registro.

## Assumptions

- El modelo de embeddings del piloto es `qwen3-embedding:0.6b` local (validado 8/9,
  28-jul); la sede necesita `ollama pull qwen3-embedding:0.6b` (639 MB) — entra al
  INSTALL y al preflight de la visita.
- «Auto» v1 aplica al plano de chat (Playground + portal); /gw responde default local si
  recibe `model=auto` (coding tools declaran modelo explícito). v2 podría extenderlo.
- El AutoRouterPanel de llm-guardian se porta como base visual pero adaptado al design
  system de la 029 y embebido en «Modelos & Ollama» (no página aparte).
- El ascii-fold de llm-guardian era workaround de un bug del proxy Azure; con embeddings
  locales se elimina (bump de versión de cache de vectores).
- La edición de rutas es admin-only; multi-tenant hereda el patrón de config por tenant
  cuando el producto lo sea (Principio III forward-looking, sin bloquear v1).
