# Diagramas — Guardian App Ecosystem

Norma de la casa para cualquier diagrama del repo. Capa **encima** de
[`DevFlow-SentinelGuardian.md`](DevFlow-SentinelGuardian.md) §4 (las tres superficies de doc):
esa dice *qué* superficie tocar, esta dice *qué dibujo* va y *cuándo está permitido
publicarlo*.

Nace de una auditoría de los 28 diagramas del repo (13-ago-2026): **17 tenían el tipo
mal elegido** — 21 de 28 eran `flowchart`/`graph`, la caja-y-flecha por defecto — y 7
afirmaban cosas que el código no hacía. El problema no era el talento de nadie: no
había norma, así que todo el mundo agarraba el tipo genérico.

## 1 · La regla, en una línea

> **Elegí el tipo por lo que el diagrama SIGNIFICA, no por lo que es fácil de dibujar.
> Y verificá el contenido contra el código antes de publicarlo.**

Un diagrama del repo no está terminado hasta que pasa las dos: tipo correcto (§3) y
contenido verificado (§5).

## 2 · Referencia de tipos

Usamos la taxonomía del skill **[`diagram-design`](https://github.com/cathrynlavery/diagram-design/tree/f3622cf66a3c557cb2ead57b687a3c1ff63f5a2b)**
(MIT) — 27 tipos con tabla de decisión. **Pineado al commit `f3622cf` (13-ago-2026)**: es
un repo activo (cambió el mismo día que se escribió esta norma), y un enlace a `main`
sin pin puede dejar de mostrar lo que esta norma describe. No la reescribimos: la
referenciamos y le agregamos nuestras reglas. Lo que sí es nuestro y es autocontenido
—no depende del pin— es §3 (los casos traducidos), §4 (las restricciones de la casa) y
§5 (la verificación).

Del skill adoptamos también su presupuesto de complejidad, que es su mejor idea:

| Límite | Valor |
|---|---|
| Nodos por diagrama | **9** |
| Flechas | 12 |
| Elementos con acento | 2 |

Pasado el límite se parte en **overview + detalle**. Hoy 6 de nuestros diagramas lo
exceden; el peor tiene 17 nodos.

## 3 · Qué tipo va en cada caso nuestro

| Si estás mostrando… | Tipo | Ejemplo nuestro |
|---|---|---|
| Containers/servicios y cómo se conectan | **Architecture** | El stack en `overview/`, la VPC y el bundle air-gap en `install-deploy/infrastructure.md` |
| Qué herramientas entran, por dónde salen y quién consume | **DP integration** | El mapa de superficies de `integrations/` — fuentes (Claude Code, Aider, Copilot, Cursor, extensión) → core (gateway) → consumidores (proveedor LLM, modelo propio) |
| Qué le pasa al dato en cada paso del pipeline | **Data flow** | El pipeline de masking→…→unmask del `overview/`; el brand-pack derivándose a runtime y a build |
| Controles agrupados por dónde se aplican | **Layer stack** | La gobernanza de `administration/gobernanza.md`; el mapa config/enforcement/evidencia de `compliance/` |
| Tres roles pasándose artefactos | **Swimlane** | Fabricante → distribuidor → cliente en `install-deploy/` |
| Etapas secuenciales sin decisiones | **Process** | La capacitación del partner; el procedimiento DSR de 7 pasos |
| Lógica con ramas y condiciones reales | **Flowchart** | Clasificación de riesgo del AI Act; triage de `operations/`; alta gateada 402/403 |
| Mensajes entre actores en el tiempo | **Sequence** | El flujo de la extensión; la instalación; el true-up de licencias |
| Estados y transiciones con guardas | **State machine** | El ciclo de vida de la licencia; las capas de gobernanza de la spec 027 |
| Entidades, campos y relaciones | **ER / data model** | El modelo de datos de las specs |
| Jerarquía padre → hijos | **Tree** | Tenant → grupo → cliente → connection; la taxonomía de gotchas |
| Tareas y fases en un calendario | **Gantt** | Los planes de fase de `specs/*/tasks.md` |
| Niveles de calidad del dato con políticas de acceso | **Medallion** | *Ninguno hoy.* Aplica el día que la auditoría tenga capas bronze/silver/gold |

**Las dos trampas que nos cazaron 17 veces:**

1. **Un `flowchart` sin rombos no es un flowchart.** Si no hay ninguna decisión, es un
   **Process** (o directamente una lista numerada). Nos pasó en el procedimiento DSR
   y en la capacitación del partner.
2. **`graph TB` con `subgraph` casi nunca es lo correcto.** Si los subgraphs son
   *capas*, es **Layer stack**; si son *zonas de infraestructura*, es **Architecture**;
   si son *roles*, es **Swimlane**.

Y la regla de deletar, que también es del skill: **si una tabla de tres columnas dice lo
mismo, va la tabla.** Un diagrama que no enseña más que un párrafo bien escrito es
trabajo de mantenimiento sin contrapartida.

## 4 · Formato: dos regímenes

No hay un formato único, porque las restricciones son genuinamente distintas a los dos
lados. Lo que **sí** es único es la tabla de tipos de §3: aplica en los dos.

| | `docs/` y `docs-cliente/` | `tech-team/` |
|---|---|---|
| Qué es | **Se vende / se entrega** al cliente | Interno: overviews, sprint reviews, tracking |
| Formato | **Mermaid como código** (fence ` ```mermaid `) | HTML editorial autocontenido |
| Marca | **Neutra** — el sitio es white-label | Nuestra marca, sin problema |
| Por qué | Versionable, diffeable, marca-neutro por construcción, y el 0-egress ya está resuelto por el plugin `privacy` | No se vende, no es white-label, y el diagrama ES el entregable |

**Por qué no migramos `docs/` a HTML editorial:** el sitio de producto es white-label
(una imagen de docs por marca, [`white-label/index.md`](../docs/docs/white-label/index.md)),
y un diagrama con nuestra paleta horneada obligaría a rebuildearlo por cliente. El
tipo de diagrama es una decisión semántica y se puede aplicar igual en Mermaid; la
marca no. Si algún día el white-label deja de ser requisito, esto se revisa.

### Air-gap: 0 egress, sin excepciones

- Los dos sitios mkdocs tienen el plugin **`privacy`** activo, que embebe cualquier
  asset externo en build. Mermaid ya viaja embebido y verificado.
- **Cuidado con el HTML de `tech-team/`**: ahí no hay build que reescriba nada. Si un
  diagrama editorial trae `<link href="https://fonts.googleapis.com/…">`, sale a
  internet. Las fuentes del skill (Instrument Serif, Geist, Geist Mono) son **OFL-1.1**
  y se pueden vendorizar; si se vendorizan, el texto de la licencia **viaja con ellas**
  (`THIRD_PARTY_LICENSES.md`, que hoy el repo no tiene).
- **El gate SÍ audita esto — corregido 13-ago, lo había afirmado mal.** Además de
  navegar el sitio con `--network none`, `deploy/release/checks/test_docs_image.sh`
  hace un grep estático sobre el HTML/CSS publicado buscando `src=`/`href=` y
  `url()`/`@import` con `http(s)://`, y **falla el build** si encuentra alguno
  (`test_docs_image.sh:35-42`). Verificado leyendo el script, no asumido. Dos huecos
  reales que sí quedan: no escanea `tech-team/` (ese HTML no pasa por este build en
  absoluto) y el grep de CSS mira archivos `.css`, no un `url(...)` metido en un
  atributo `style="..."` inline dentro del HTML.

## 5 · Verificar el contenido — el paso que faltaba

Tipo correcto y contenido falso sigue siendo una mentira. De la auditoría: el diagrama
del ciclo de vida de la licencia tenía el tipo **bien** elegido y modelaba `hard_block`
como un estado cuando en el código es un *toggle de entorno*.

Antes de publicar un diagrama, verificá **en el fuente del otro lado**:

| Si el diagrama muestra… | Comprobalo contra |
|---|---|
| Un endpoint | `docs/docs/api-reference/openapi.json` (y el decorador que lo declara) |
| Una variable de configuración | Que el código la lea de verdad — no que exista en `.env.example` |
| Un código o literal de error | Que el código lo emita con ese nombre exacto |
| Un container o servicio | `deploy/docker/compose.prod.yml`, que es el stack real de producción |
| Un estado de una máquina de estados | Que sea un estado y no una perilla de config |

Para los tres primeros ejes hay instrumento:

```bash
python3 docs/tools/drift_gate.py
```

Emite veredicto `PASS`/`FAIL` y tabla. **`documentado_no_existe` es una mentira y tiene
prioridad sobre cualquier otra tarea de documentación.** `existe_no_documentado` es un
hueco: entra al backlog, no bloquea.

La regla de la que salió todo esto, y que aplica aunque no corras nada: **un claim que
cruza de plano se lee en el fuente del otro lado antes de escribirlo, o no se escribe.**

## 6 · Checklist antes de abrir el PR

- [ ] El tipo sale de la tabla de §3 — y si es `flowchart`, tiene decisiones de verdad
- [ ] ≤ 9 nodos (si no, está partido en overview + detalle)
- [ ] Una tabla no haría el mismo trabajo
- [ ] Contenido verificado contra el fuente del otro lado (§5)
- [ ] `python3 docs/tools/drift_gate.py` sin mentiras nuevas
- [ ] Superficie correcta y régimen de formato correcto (§4)
- [ ] Si es `tech-team/` con HTML: cero assets remotos
- [ ] `mkdocs build --strict` verde del sitio que tocaste

---

Dueño: DevRel-Documentation («La Imprenta» 📰) · depto Guardian.
Creado 2026-08-13 a partir de la auditoría de los 28 diagramas del repo.
