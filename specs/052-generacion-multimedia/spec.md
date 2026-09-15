# Feature Specification: Generación de imagen, audio y video en Eleia Hub

**Feature Branch**: `052-generacion-multimedia`

**Created**: 2026-09-15

**Status**: 🔬 **INVESTIGACIÓN PENDIENTE — no arrancada.** Mismo molde que la
[spec 051](../051-historial-planillas/spec.md): primero se investiga y se entrega un
`RESULTADOS.md`, después se decide si hay spec de implementación. Registra la intención del dueño
del producto (15-sep-2026) de que Eleia genere también imagen, audio y video. **Todavía no hay
alcance cerrado ni nada comprometido para el piloto** — lo que hay es una tarea de investigación
con preguntas y entregables definidos (§3 y §6).

**Referencia cruzada**: `ELEIA-052` (convención de ADR-0007 para specs 039+).

**Repos que tocaría**: `client/` (Eleia Hub) y despliegue. Motor nuevo, contenedor aparte, mismo
patrón que los otros — **no** toca `backend/` salvo el registro de la llave de servicio.

**Input**: pedido del dueño del producto, 15-sep-2026: *"dejá abierto para más adelante la
creación de video, audio e imágenes"*.

---

## 1. Por qué existe esta investigación

La [spec 049](../049-motor-generacion-documentos/spec.md) define el motor de documentos
(`docx/xlsx/pdf`) y la [050](../050-ia-hub-conector-motores/spec.md) ya dejó a Presenton generando
presentaciones. Las dos comparten un patrón que **conviene no romper** cuando aparezca lo
multimedia:

| Pieza | Dónde está definida | Por qué sirve igual para multimedia |
|---|---|---|
| Motor en contenedor aparte, red propia, token interno + `X-Hub-User-Id` | [050 `contracts/03-motores.md`](../050-ia-hub-conector-motores/contracts/03-motores.md) | Un motor de imagen/audio/video es "otro motor más", no una excepción |
| Entrega por **URL firmada** del gateway, nunca base64 en la respuesta | 049 FR-011 | Un `.mp4` embebido en el contexto del modelo es el mismo problema, multiplicado por el tamaño |
| Presupuesto y atribución por persona | 049 FR-005, 050 | Generar video es **caro**: sin esto no hay control de costos |
| Errores neutros, sin nombrar la herramienta | 049 FR-010 | Regla de marca vigente |
| "Mis archivos generados" como lugar único de descarga | 050 (UI única) | El usuario no debería aprender un lugar nuevo por cada tipo |

**El riesgo que esta investigación evita:** que el motor 4 se construya asumiendo "documentos" en el
nombre de las rutas, el modelo de datos y la UI, y que meter video después obligue a rehacerlo.

## 2. Lo único que ya se puede afirmar

- **No entra en el piloto.** El piloto es chat, planillas, presentaciones y documentos.
- **Va como motor aparte**, no dentro de docgen. Las toolchains no se parecen en nada (ffmpeg y
  modelos de difusión no comparten con `docxtpl`).
- **Mismo contrato de identidad, presupuesto y entrega** que los motores existentes (tabla de §1).
- **El enmascarado tiene que pensarse distinto.** Hoy la PII se detecta y se enmascara sobre
  **texto**. Un prompt de imagen puede llevar el nombre de una persona; un audio generado puede
  pronunciarlo. Eso **no está resuelto** para estos formatos y es la pregunta más seria de las
  de abajo.

## 3. Preguntas que la investigación tiene que responder

1. **¿Local o API externa?** Es la decisión que define todo lo demás. Un modelo de difusión o de
   voz local necesita GPU (el servidor de Elea hoy no la tiene, y ya tuvo problemas de disco); una
   API externa saca el contenido de la instalación, que es exactamente lo que el producto vende
   que no pasa. **Sin responder esto, el resto no se puede planificar.**
2. **¿Qué pasa con la PII en un prompt de imagen o en un audio?** El pipeline de enmascarado es
   de texto. ¿Se enmascara el prompt antes de salir? ¿Un audio con una voz diciendo un DNI es un
   dato personal a auditar? ¿Qué se registra en la auditoría cuando la salida no es texto?
3. **¿Qué casos de uso reales pidió el cliente?** Hoy no hay ninguno documentado: esto sale de
   "dejalo abierto", no de un pedido concreto de Elea. Sin casos de uso no hay alcance.
4. **¿Cómo se gobierna el costo?** Un video puede costar órdenes de magnitud más que un chat.
   ¿Presupuesto aparte? ¿Tope por pieza? ¿Aprobación previa?
5. **¿Derechos sobre lo generado, y marca de agua?** Para una farmacéutica, material generado por
   IA con la marca puede tener implicancias regulatorias (publicidad de medicamentos). Hay que
   consultarlo antes de habilitarlo, no después.
6. **¿Entra en el alcance del EU AI Act / Ley 25.326?** Generar imagen o audio de personas
   reales toca biometría y consentimiento. La [spec 005](../005-compliance-policies-gdpr-ai-act/)
   no lo cubre.

## 4. Qué NO hacer mientras tanto

- **No** poner `documento` en nombres de rutas, tablas o entidades del motor 4 si un nombre neutro
  (`artefacto`, `archivo generado`) cuesta lo mismo. La 050 ya usa "mis archivos generados" en la
  UI — mantener ese vocabulario.
- **No** construir el visor de descargas asumiendo que todo lo generado se abre en Office.
- **No** prometerlo al cliente. Esto es una investigación interna, no una funcionalidad anunciada.

## 5. Criterios para elegir

En este orden, y el primero manda sobre los demás:

1. **Que no saque contenido de la instalación.** Es lo que el producto vende. Una opción externa
   sólo entra si hay una respuesta convincente a qué sale, adónde y con qué contrato.
2. **Que el enmascarado siga valiendo.** Si no hay forma de proteger PII en ese formato, la opción
   no sirve por más barata que sea.
3. **Que corra en el hardware que hay** — o que el costo del hardware que falta esté cuantificado.
   El servidor de Elea no tiene GPU y ya tuvo problemas de disco.
4. **Costo por pieza acotado y medible**, para que entre en el mismo control de presupuesto.
5. **Licencia compatible** con distribuir el producto, como se evaluó en las investigaciones de
   docgen.

## 6. Entregables de la investigación

- `RESULTADOS.md` en esta carpeta con las respuestas a las 6 preguntas de §3, con **mediciones
  reales** donde aplique (costo por pieza, tiempo, requisitos de hardware), no sólo lectura de
  documentación.
- Una recomendación **con opción elegida y descartadas**, en el molde de las dos investigaciones
  de docgen — incluyendo la opción "no hacerlo", que es legítima si las respuestas son malas.
- Si la recomendación es seguir: contrato propuesto del motor, en el molde de
  [050 §3.4](../050-ia-hub-conector-motores/contracts/03-motores.md).
- Qué habría que tocar del motor 4 **antes** de que se construya, si es que algo — que es la razón
  por la que esta investigación conviene que se haga temprano aunque la implementación sea tarde.

## 7. Criterio de cierre

La investigación se da por cerrada con el `RESULTADOS.md` entregado. Recién ahí se decide si nace
una spec de implementación.

Hasta entonces, cualquiera que lea esto debe saber que **no hay trabajo de implementación
comprometido**.
