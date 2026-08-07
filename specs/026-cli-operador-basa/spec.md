# Feature Specification: CLI de operador (`basa-admin`) — firma de licencias e instalación guiada offline

**Feature Branch**: `026-cli-operador-basa`

**Created**: 2026-07-22

**Status**: Draft

**Input**: User description: "Una CLI buena que ayude a un humano a hacer lo necesario sin correr scripts horribles. Herramienta local y offline (no rompe airgap, no phone-home, produce archivos). MVP: firma de licencias e instalación mínima de un cliente hasta stack corriendo y verificado. Absorbe los issues #33 (firma) y #34 (password admin). El resto (día-2, cloud, docs brand) es fase 2."

## Contexto (por qué ahora)

Hoy operar el producto es un conjunto de **scripts sueltos, sin flags, sin validación y con foot-guns silenciosos** (inventario vivo del 2026-07-22, 54 operaciones relevadas). Los tres peores, verificados en el código:

- **`issue_dev_license.py`** no recibe argumentos: el payload (tenant, seats, expiry, kid) está **hardcodeado** en el fuente, y **cada corrida regenera el par Ed25519 y sobrescribe el keyset público** — invalidando en silencio **toda caja ya instalada** con el keyset viejo. No hay flujo de producción: firmar de verdad es editar código.
- **`apply_profile_seed.py`** toma dos argumentos posicionales y hace `commit()` sin confirmación ni dry-run; un slug equivocado **renombra el tenant productivo** en silencio.
- **`generate_trueup.py`** vuelca el JSON firmado a **stdout**: si falta el `>` se pierde; el envío a Basa es un paso humano fuera de banda sin tracking.

Sumado a esto, el bootstrap/rotación del admin es **SQL crudo** (issue #34), y hay **3 fixes de deploy que viven fuera del repo** (issue #35). Esto es exactamente lo que frena instalar en un partner de forma **repetible y digna** (repo limpio, sin "corré este script y rezá"). Esta feature convierte esas operaciones en **comandos guiados, validados y seguros** de una CLI local — la forma madura del issue #33.

**Regla dura, no negociable**: la CLI **no rompe el modelo airgap**. Es una herramienta **local** que corre en el host (o en la máquina de firma de Basa), **produce y consume archivos**, y **jamás hace phone-home**. La verificación de licencias sigue siendo 100% offline; el true-up y el registro de la deployment key viajan como **archivos** fuera de banda, no como tráfico del producto hacia el fabricante.

## Clarifications

### Session 2026-08-05

- **Q**: ¿La CLI se distribuye como un único binario universal (con comandos de firma y de
  instalación dentro, gateados por rol/flag) o como artefactos físicamente separados? →
  **A**: **Dos artefactos físicamente separados**: `basa-admin-signer` (herramienta interna de
  firma de Basa: emisión de licencias, custodia de clave privada PKCS8 cifrada, import/unlock
  de clave, rotación de clave del emisor, export del keyset público, ledger de emisiones,
  verificación de licencias — corre solo en la estación de firma aislada de Basa, nunca se
  entrega a partners/clientes ni se incluye en el bundle air-gapped) y `basa-admin` (herramienta
  de partner/cliente: perfil, secretos, bundle, load, up, seed, instalación/verificación de
  licencia, bootstrap de admin, estado/verificación de instalación — NO contiene físicamente
  código de emisión, custodia de clave privada de Basa, rotación de clave del emisor, comandos
  exclusivos de firma, ni módulos del signer transitivamente importables).
- **Q**: ¿El ocultamiento en runtime (subcomandos Click ocultos, flags de rol, gates por
  variable de entorno, gates de comando parchables en un binario universal) es un límite de
  seguridad aceptable para separar firma de instalación? → **A**: **No**. Ninguna forma de
  ocultamiento en runtime es un límite de seguridad válido; la separación es física (dos
  artefactos) y se decide en build time.
- **Q**: ¿Cómo se aplica y verifica esa separación? → **A**: En **build time**, con dos tests
  obligatorios: un contract test para `basa-admin-signer`, y un test de inspección de artefacto
  que falla el build si `basa-admin` contiene módulos, símbolos, comandos o dependencias
  exclusivos del signer.
- **Q**: ¿Qué va dentro del bundle air-gapped y con qué layout? → **A**: Únicamente
  `basa-admin` (nunca `basa-admin-signer`). Layout esperado:
  `bundle-v<version>.tar.gz` con `bin/{basa-admin-x86_64.pyz, basa-admin-arm64.pyz}`,
  `images/`, `manifests/`, `profiles/`, `install.sh`.
- **Q**: ¿Qué garantías deben cumplir los `.pyz` operacionales y cómo se instala `basa-admin`
  en el host air-gapped? → **A**: Los `.pyz` deben figurar en el MANIFEST con validación
  SHA-256, compartir la misma versión de release que imágenes/migraciones/perfiles/manifests,
  incluir dependencias específicas de arquitectura, correr sin descargas, y requerir solo
  Python 3.11+ y Docker en el host destino. `basa-admin` NUNCA se instala vía pip, apt, yum ni
  repositorios externos dentro del entorno air-gapped — la única vía es el `.pyz` del bundle.
  Matriz de despliegue: estación de firma de Basa → `basa-admin-signer`; máquina de build/CI
  del partner → `basa-admin`; host air-gapped del cliente → `basa-admin` empaquetado en el
  bundle.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Firmar una licencia sin foot-guns (Priority: P1)

Un humano de Basa (con la clave privada de firma custodiada) necesita emitir un `.lic`
firmado para un cliente nuevo de un partner: tenant, cantidad de seats y expiry. Lo hace
con **un comando y flags**, sin editar código y sin correr riesgo de invalidar cajas ya
instaladas.

**Why this priority**: es la **precondición dura de todo lo demás**. Sin un `.lic` firmado
(y el keyset público que lo verifica) la caja arranca pero entra en fail-closed y rechaza
toda alta de Connection/usuario (403/402) — no se puede seedear ni entregar un cliente.
Hoy firmar es un script dev senior-only que además **rota claves por accidente**. Convertir
la firma en un comando seguro desbloquea vender, instalar y renovar. Es el primer ladrillo.

**Independent Test**: con la clave privada disponible, emitir un `.lic` de producción por
flags contra un tenant/seats/expiry dados; verificar que el archivo resultante valida
offline contra el keyset publicado, y que **el keyset público existente NO fue tocado**.

**Acceptance Scenarios**:

1. **Given** la clave privada de firma custodiada, **When** el operador ejecuta la emisión
   con `--tenant`/`--seats`/`--expiry`, **Then** se produce un `.lic` firmado que valida
   offline, sin editar ningún fuente.
2. **Given** un keyset público ya existente, **When** el operador emite una licencia sin
   pedir rotación explícita, **Then** el keyset **no se regenera ni se sobrescribe** (la
   rotación solo ocurre con un flag explícito y con aviso).
3. **Given** una emisión de licencia, **When** se genera la clave privada o se la usa,
   **Then** nunca queda escrita en claro en disco (cifrada en reposo).
4. **Given** el keyset público del emisor, **When** el operador lo exporta, **Then** obtiene
   un archivo (kid + clave) apto para embeber/distribuir, sin exponer la privada.

---

### User Story 2 - Instalar un cliente de cero a corriendo, guiado (Priority: P1)

Un ingeniero (de Basa o del partner) instala un cliente nuevo: arma el perfil, genera
secretos, transfiere el bundle air-gapped, levanta el stack, siembra el tenant, instala la
licencia, hace bootstrap del admin y verifica — **cada paso validado, con confirmación y
dry-run donde muta datos**, sin editar scripts ni correr SQL a mano.

**Why this priority**: es el otro medio del MVP. Junto con US1 permite **dejar el primer
cliente corriendo y verificado** por el camino humano. Es lo que hace que onboardear a
Cámara (piloto) no sea "corré 6 scripts y rezá".

**Independent Test**: partiendo de un `.lic` firmado (US1), correr la secuencia de
instalación de la CLI de punta a punta contra un host limpio y terminar con el smoke test
en verde, sin haber editado ningún archivo de script ni ejecutado SQL manual.

**Acceptance Scenarios**:

1. **Given** un host limpio y un `.lic` firmado, **When** el operador corre la secuencia
   guiada (perfil → secretos → bundle/carga → up → seed → licencia → admin → verify),
   **Then** el stack queda corriendo y el smoke test end-to-end pasa.
2. **Given** un seed que renombraría el tenant, **When** el operador lo aplica, **Then** la
   CLI muestra el cambio (dry-run/diff) y **pide confirmación** antes de commitear.
3. **Given** un bundle air-gapped al que le falta una de las imágenes, **When** se lo
   verifica, **Then** el faltante se detecta **antes** de transferir/cargar — nunca se
   intenta un pull en runtime en la caja airgap.
4. **Given** un host, **When** el operador va a mutar la base, **Then** la CLI valida a qué
   deployment/DB apunta antes de tocar nada (no "pegarle a la DB equivocada" en silencio).
5. **Given** el bootstrap del primer admin, **When** se define su password, **Then** se pasa
   por prompt/stdin (nunca por argumento ni por SQL a mano) — reemplaza el `UPDATE` crudo.

---

### User Story 3 - Operar el día-2 sin SQL crudo (Priority: P3, fase 2)

El operador de una caja instalada hace tareas recurrentes — rotar la password del admin,
exportar el true-up para renovación, consultar el estado de la licencia, rotar el keyset o
la deployment key — con comandos seguros, sin entrar al contenedor a correr SQL.

**Why this priority**: son operaciones de día-2, valiosas pero que **no bloquean dejar el
primer cliente corriendo**. Entregables por separado, después del MVP.

**Independent Test**: sobre una caja ya instalada, rotar la password del admin y exportar un
true-up firmado usando solo comandos de la CLI; verificar que no se ejecutó ningún SQL manual
y que el true-up valida offline.

**Acceptance Scenarios**:

1. **Given** una caja instalada, **When** el operador rota la password del admin, **Then** se
   aplica sin un solo `UPDATE` a mano (absorbe issue #34).
2. **Given** una caja instalada, **When** el operador exporta el true-up, **Then** obtiene un
   archivo firmado con nombre correcto (no a stdout) apto para enviar fuera de banda.

---

### Edge Cases

- **Keyset ya existente sin rotación explícita** → la emisión no lo toca; jamás lo regenera en
  silencio (el bug histórico de `issue_dev_license.py`).
- **Seed con slug equivocado** → dry-run muestra el rename del tenant y exige confirmación;
  nunca renombra la instancia productiva en silencio.
- **Bundle incompleto** (falta una de las 7 imágenes) → detectado en `verify` antes de la
  transferencia; en la caja airgap nunca se dispara un pull en runtime.
- **DB equivocada** → la CLI identifica/pregunta a qué deployment apunta antes de mutar.
- **Licencia dev en deployment de producción** → respeta el guard existente
  (`BASA_ALLOW_DEV_LICENSE`); no permite mezclar dev/prod en silencio.
- **Comando que requiere red ejecutado en la caja del cliente** (`release publish`,
  `cloud apply`) → la CLI lo rechaza/avisa: esos viven en la máquina de build del partner,
  nunca en la caja airgapped.
- **Secretos/virtual keys** → siempre a archivo con permisos restringidos; nunca a stdout ni
  a logs.
- **Build de `basa-admin` que arrastra código/dependencias del signer** → el test de
  inspección de artefacto (build time) DEBE fallar el build antes de que pueda distribuirse.
- **`basa-admin-signer` incluido por error en el armado del bundle air-gapped** → nunca debe
  ocurrir; el proceso de empaquetado del bundle solo toma `basa-admin` como entrada.
- **Intento de separar firma de instalación solo con un flag de rol o variable de entorno en un
  binario único** → rechazado como solución válida; la separación es física (dos artefactos),
  no runtime.

## Requirements *(mandatory)*

### Functional Requirements

**Núcleo — firma (US1, MVP) — exclusivo de `basa-admin-signer`**

- **FR-001**: `basa-admin-signer` DEBE emitir un `.lic` de producción firmado tomando el
  payload (tenant, seats, expiry, feature flags, grace) por **flags/parámetros**, sin editar
  código.
- **FR-002**: La emisión NUNCA DEBE regenerar ni sobrescribir el keyset público salvo con una
  **acción de rotación explícita**; ante un keyset ya existente DEBE avisar y no pisarlo por
  defecto (corrige el foot-gun crítico verificado en `issue_dev_license.py`).
- **FR-003**: La clave privada de firma NUNCA DEBE quedar escrita en claro en disco; se maneja
  **cifrada en reposo (PKCS8)** dentro de `basa-admin-signer` y se usa sin exponerla.
- **FR-004**: `basa-admin-signer` DEBE poder **exportar el keyset público** (kid + clave) como
  archivo para embeber/distribuir, sin exponer la privada.

**Núcleo — instalación (US2, MVP) — exclusivo de `basa-admin`**

- **FR-005**: `basa-admin` DEBE cubrir el camino de **cero a stack corriendo y verificado**:
  crear y renderizar el perfil del cliente, generar secretos, empaquetar/cargar el bundle
  air-gapped (o levantar el compose), sembrar el tenant, instalar la licencia (con registro de
  génesis), hacer bootstrap del admin y correr el smoke test — cada paso con **validación de
  precondiciones** y mensajes de error legibles (no tracebacks crudos).
- **FR-006**: Toda operación que mute datos productivos (seed que renombra tenant, instalación
  de licencia) DEBE ofrecer `--dry-run` (mostrar el cambio sin commit) y **pedir confirmación**
  antes de aplicar.
- **FR-007**: Antes de mutar la base, `basa-admin` DEBE **validar a qué deployment/DB apunta**;
  no puede modificar una instancia equivocada en silencio.
- **FR-008**: El bootstrap y la rotación del admin DEBEN hacerse **sin SQL crudo**; la password
  se ingresa por prompt/stdin, nunca por argumento ni por `UPDATE` manual (absorbe issue #34).
- **FR-009**: Secretos y virtual keys generados DEBEN escribirse a **archivos con permisos
  restringidos**, nunca a stdout ni a logs.
- **FR-010**: `basa-admin` DEBE ofrecer una **verificación end-to-end** post-deploy
  (contenedores arriba, licencia activa, gateway responde, masking/bloqueo en vivo) que salga
  en rojo si algo falla.

**Transversales (ambos artefactos)**

- **FR-011**: Todos los comandos del núcleo (firma en `basa-admin-signer` + instalación y
  operación día-2 en `basa-admin`) DEBEN correr **offline, sin egress ni phone-home**,
  operando solo sobre archivos y sobre el host local. Cualquier comando que requiera red
  (build/publish/cloud) DEBE estar **separado y marcado explícitamente**, y DEBE impedirse/
  avisarse su ejecución en la caja del cliente.
- **FR-012**: `basa-admin-signer` y `basa-admin` DEBEN, entre los dos, **reemplazar** (no
  envolver indefinidamente) los scripts sueltos `issue_dev_license.py`,
  `apply_profile_seed.py`, `generate_trueup.py` y los
  `render_profile.sh`/`bundle.sh`/`publish.sh`/`render_docs_brand.sh`; los scripts quedan
  deprecados con puntero al artefacto correspondiente y una ruta de migración.
- **FR-013**: Cada operación relevante (emisión, instalación, seed, rotación) DEBE dejar
  registro en un **audit-log local** (sin red), exportable como archivo — trazabilidad sin
  egress, coherente con el pilar de auditoría del producto.
- **FR-014**: La CLI DEBE reutilizar los contratos existentes — formato `.lic` y verificación
  Ed25519 (021), modelo de perfil/seed y bundle air-gapped (020/013) — sin redefinirlos ni
  parchear el motor (Principio VI).

**Día-2 (US3, fase 2 — alcance, fuera del MVP)**

- **FR-015**: La CLI DEBE ofrecer un espacio de comandos de **día-2** (rotar password, export
  de true-up con nombre correcto, estado de licencia offline, rotación de keyset/deployment
  key, backup/restore) — sin SQL crudo y airgap-safe. Estos NO forman parte del MVP.

**Empaquetado y frontera de confianza (transversal, MVP)**

- **FR-016**: La solución DEBE producirse como **dos artefactos físicamente separados**:
  `basa-admin-signer` (herramienta interna de firma de Basa) y `basa-admin` (herramienta de
  instalación/operación offline para partners/clientes). NO DEBE existir un binario único que
  combine ambos roles.
- **FR-017**: `basa-admin-signer` corre únicamente en la estación de firma aislada de Basa;
  puede contener emisión de licencias, custodia de la clave privada de firma en PKCS8 cifrada,
  import/unlock de clave, rotación de la clave del emisor, export del keyset público, ledger de
  emisiones y verificación de licencias. NUNCA DEBE entregarse a partners/clientes ni incluirse
  en el bundle air-gapped del cliente.
- **FR-018**: `basa-admin` puede contener los comandos de perfil, secretos, bundle, load, up,
  seed, instalación/verificación de licencia, bootstrap de admin, y estado/verificación de
  instalación. NO DEBE contener físicamente — ni como módulo transitivamente importable —
  código de emisión de licencias, custodia de la clave privada de Basa, rotación de la clave
  privada del emisor, ni ningún comando exclusivo de firma.
- **FR-019**: El ocultamiento en runtime NO es un límite de seguridad válido para esta
  separación: NO DEBE implementarse vía subcomandos Click ocultos, flags de rol, gates por
  variable de entorno, ni gates de comando parchables dentro de un ejecutable universal.
- **FR-020**: La separación entre `basa-admin-signer` y `basa-admin` DEBE aplicarse en **build
  time** y verificarse con tests: un contract test para `basa-admin-signer`, y un test de
  inspección de artefacto que **falle el build** si `basa-admin` contiene módulos, símbolos,
  comandos o dependencias exclusivos del signer.
- **FR-021**: El bundle air-gapped DEBE distribuir únicamente `basa-admin` (nunca
  `basa-admin-signer`), con el layout:

  ```
  bundle-v<version>.tar.gz
  ├── bin/
  │   ├── basa-admin-x86_64.pyz
  │   └── basa-admin-arm64.pyz
  ├── images/
  ├── manifests/
  ├── profiles/
  └── install.sh
  ```

- **FR-022**: Los artefactos `.pyz` operacionales DEBEN: figurar en el MANIFEST con validación
  SHA-256; compartir la misma versión de release que imágenes, migraciones, perfiles y
  manifests; incluir dependencias específicas de arquitectura; correr **sin descargas**; y
  requerir solo **Python 3.11+ y Docker** en el host destino.
- **FR-023**: `basa-admin` NO DEBE instalarse vía pip, apt, yum ni repositorios externos dentro
  del entorno air-gapped; la única vía de instalación es el `.pyz` incluido en el bundle.

### Key Entities *(include if feature involves data)*

- **`basa-admin-signer`** (artefacto separado, interno Basa): herramienta de la estación de
  firma aislada — emisión de licencias, custodia/rotación de la clave privada del emisor,
  export del keyset público, ledger de emisiones, verificación. Nunca se distribuye a
  partners/clientes ni viaja en el bundle air-gapped.
- **`basa-admin`** (artefacto separado, distribuido en el bundle): herramienta de
  instalación/operación offline para partners/clientes — perfil, secretos, bundle, load, up,
  seed, instalación/verificación de licencia, bootstrap de admin, estado/verificación. No
  contiene físicamente código, claves ni comandos exclusivos del signer.
- **Licencia `.lic`**: artefacto firmado (definido en 021) — `basa-admin-signer` lo **produce**
  (US1) y `basa-admin` lo **instala** (US2). No redefine su formato.
- **Keyset público del emisor** (kid + clave): `basa-admin-signer` lo **exporta**; jamás lo pisa
  sin rotación explícita.
- **Clave privada de firma**: custodiada, cifrada en reposo (PKCS8), solo dentro de
  `basa-admin-signer` en la estación de firma de Basa — se usa para firmar sin exponerla; nunca
  existe en `basa-admin`.
- **Perfil de cliente** (config + branding + env): `basa-admin` lo **scaffolda y renderiza**
  desde el ejemplo, validando el layout y las variables del template.
- **Bundle air-gapped** (tarball de imágenes + MANIFEST + `basa-admin` `.pyz` por arquitectura):
  se **crea, verifica y carga** garantizando que ninguna imagen ni artefacto falte antes de la
  transferencia; nunca incluye `basa-admin-signer`.
- **Registro de emisiones / audit-log local**: traza offline de lo que cada artefacto hizo (qué
  se emitió por tenant vía `basa-admin-signer`, qué se instaló vía `basa-admin`), exportable
  como archivo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un operador con el perfil base (Docker/shell, **no** senior del producto) instala
  un cliente de cero a stack **verificado** usando solo comandos de la CLI, sin editar ningún
  script ni correr SQL — hoy: requiere un senior editando fuentes.
- **SC-002**: 0 emisiones de licencia regeneran o pisan el keyset público sin una acción de
  rotación explícita — hoy: **cada** corrida lo pisa.
- **SC-003**: Emitir una licencia de producción no requiere editar código fuente — hoy: el
  payload está hardcodeado en el script.
- **SC-004**: La password de admin se bootstrapea/rota sin un solo `UPDATE` manual — hoy: SQL
  crudo (issue #34).
- **SC-005**: El 100% de los comandos del núcleo corre con la red cortada (verificable sin
  egress) — hoy: N/A (scripts sueltos, sin garantía).
- **SC-006**: Ninguna virtual key ni secreto aparece en stdout o logs; todos quedan en archivos
  con permisos restringidos — hoy: el true-up y las keys salen por stdout.
- **SC-007**: El tiempo y la tasa de error de un install liviano bajan de forma medible
  (calibrable contra el ensayo del VPS→main): lo ejecuta una persona no-senior siguiendo la
  CLI, sin intervención de fuentes.

## Assumptions

- **Lenguaje/runtime de la CLI = decisión del plan**: la spec es agnóstica. Go (binario único
  estático, ideal airgap) vs Python (reusa `canonical_payload_bytes`, `verifier.py` y el
  onboarding del backend) se decide en `/speckit-plan`.
- **Custodia de la privada de firma**: cifrada en reposo (age/SOPS) para el MVP; KMS/HSM es
  fase 2 (research 021 fijó **DIY Ed25519**, no firma delegada).
- **Cupo del pool**: el MVP **registra emisiones localmente** para visibilidad del humano; el
  **enforcement duro del cupo del distribuidor vive en el portal** (fase posterior, la forma
  completa del #33), no en esta CLI.
- **Reutiliza contratos existentes**: no redefine el `.lic` (021), el modelo de seed (013) ni
  el bundle/deploy (020); los envuelve con una cara humana.
- **Los 3 fixes out-of-repo (#35)** se cierran como **PR en el repo** (parte del producto), no
  como comando de la CLI — la ruta 020 los supersede.
- **Frontera con seguridad**: la custodia de claves y el RBAC de "quién puede firmar" tocan
  territorio de la 017 (Cristian) — coordinación y review cruzado.
- **Punto de ejecución** (host vs `docker exec`) se resuelve en el plan.
- **Empaquetado — DECIDIDO (ver Clarifications 2026-08-05, FR-016 a FR-023)**: dos artefactos
  físicamente separados, `basa-admin-signer` (interno Basa, estación de firma aislada) y
  `basa-admin` (partner/cliente, distribuido en el bundle air-gapped). Un binario único
  gateado por rol/flag/env var **no** es una alternativa válida; la separación se aplica en
  build time y se verifica con un contract test del signer y un test de inspección de
  artefacto sobre `basa-admin`.
- **Matriz de despliegue**: estación de firma de Basa → `basa-admin-signer`; máquina de
  build/CI del partner → `basa-admin` (se construye ahí); host air-gapped del cliente →
  `basa-admin` empaquetado dentro del bundle. `basa-admin-signer` nunca corre ni se distribuye
  fuera de la estación de firma de Basa.
- **Contexto de validación**: el MVP se prueba en el **ensayo VPS→main** y como preparación del
  **piloto de Cámara de Comercio** (cliente+partner, uso interno).
