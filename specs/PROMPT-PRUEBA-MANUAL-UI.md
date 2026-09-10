# Prompt para la sesión de prueba manual (otra ventana de Claude Code)

**Fecha**: 10-sep-2026. **Para qué**: probar de verdad, clickeando, lo que el plan de
verificación (`VERIFICACION-043-044-pruebas.md`) dejó pendiente por API/código — y
documentar los resultados en un archivo para que la sesión principal siga desde ahí.

**No levantes ni bajes el stack** — ya está arriba (`STACK_PREFIX=eleae2e`, en
`/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea`), con datos reales de sesiones
anteriores. Si en algún momento no responde, avisá en el archivo de resultados en vez de
tocar Docker.

---

## Prompt (copiar y pegar tal cual en la otra sesión)

```
Tengo un stack de Eleia Guardian + Eleia Hub ya levantado localmente para pruebas
manuales (repo: /home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea). NO lo levantes ni lo
bajes — ya está corriendo, solo conectate con el navegador (Claude in Chrome, o el
Browser pane si no tenés esa herramienta) y probá clickeando de verdad, no asumas nada
por código.

URLs:
- Panel Eleia Guardian: http://localhost:8090
- Eleia Hub (cliente/CLI): http://localhost:8095
Login en ambas: usuario "admin", contraseña "PsBoMHYDuSG4T64-U9gnYQ"

Ya hay un espacio de prueba cargado ("Contabilidad") con datos de sesiones anteriores.

Contexto: esto es la verificación de las specs 043 (aislamiento/costos/motor) y 044
(Eleia Hub + Eleia Guardian) contra los reclamos reales de Tomás Mc Nally (Elea), mail
del 03 y 07-sep. Ya se probó bastante por API/curl en sesiones anteriores — lo que falta
es la vuelta por la UI de verdad. Recorré esta lista y documentá QUÉ VISTE en cada paso
(no si "debería" andar — qué pasó de verdad, con capturas si algo se ve raro):

## Pendiente de P1 — "La memoria de chats es compartida" (el reclamo más urgente de Tomás)
1. Como admin, creá un espacio nuevo, subí un documento cualquiera (un .txt o .csv corto
   con algún dato tipo DNI/email/teléfono/nombre), hacé una pregunta sobre ese dato.
2. Andá a Usuarios & Presupuestos, creá un usuario cliente nuevo con contraseña conocida
   (anotala en el resultado).
3. Deslogueate, entrá como ese usuario nuevo en una ventana de incógnito — confirmá que
   NO ve el espacio que creó admin (debería ver el estado vacío, "Todavía no tenés
   espacios...").
4. Desde admin, agregalo como miembro de ese espacio (Miembros) → recargá con el usuario
   nuevo → debería verlo ahora.
5. Con el usuario nuevo, creá un hilo propio dentro de ese espacio y preguntá algo
   distinto — confirmá que su hilo y el de admin NO se mezclan (cada uno ve solo el
   suyo, sin ningún mensaje del otro).

## P3 por UI — reverificar el fix de cuentas de servicio (ya se corrigió por API, falta la vuelta visual)
6. Panel → Costos → Top modelos: confirmá que NO aparece "license" ni "chat-ui".
7. Panel → Usuarios & Presupuestos, tabla principal: confirmá que NO aparecen
   "svc.anythingllm-provider" ni "svc.rag-masking" ni ninguna cuenta que empiece con "svc.".
8. Desplegá la sección "Cuentas de servicio" (suele estar plegada) — ahí SÍ deberían
   aparecer, marcadas como de servicio, de solo lectura.

## Branding (se arregló ayer, confirmar que se ve bien)
9. Mirá el panel y el Hub — deberían decir "Eleia Guardian" / "Eleia Hub" CON EL LOGO
   REAL de Eleia (no un ícono genérico tipo escudo). Sacá una captura de cada uno.

## P5 — ciclo de vida de usuario (ya probado por API con un bug encontrado y arreglado, confirmar por UI)
10. En Usuarios & Presupuestos, editá SOLO el email de un usuario (no el rol) — confirmá
    que el resto de sus datos queda igual.
11. Desactivá a un usuario cualquiera (no vos) desde el toggle del panel — confirmá que
    pide algún tipo de confirmación, y que el usuario queda con badge "Desactivado".
12. Con la sesión de admin, intentá desactivarte A VOS MISMO — la UI debería impedirlo
    con una explicación clara, SIN que llegue a mandar el pedido (mirá la pestaña Network
    si podés, no debería haber ningún request).

## Exploración libre
13. Navegá el resto del panel (Seguridad, Gobernanza, Compliance si existe) y el Hub
    (selector de modelo, presupuesto visible en el Hub) — anotá cualquier cosa que se
    vea rota, con nombres técnicos filtrados (AnythingLLM/LiteLLM/Presidio), textos que
    no tengan sentido, o errores en consola del navegador.

## NO es necesario probar (ya identificado como fuera de alcance, no lo reportes como bug nuevo)
- Preguntas tipo "sumá la columna X" o cruces entre archivos CSV/Excel — el motor actual
  es búsqueda semántica por chunks, no tabular. Ya trackeado aparte (spec 046, necesita
  un motor nuevo tipo DB-GPT, decisión ya tomada de dejarlo fuera del piloto).
- El costo de preguntas hechas DENTRO de un espacio (RAG) atribuido al usuario real en
  Costos — es una limitación arquitectónica ya documentada y aceptada por ahora (el chat
  DIRECTO sin espacio sí atribuye bien, podés confirmar eso si querés, pero el de RAG no
  hace falta reportarlo de nuevo).

Cuando termines, ESCRIBÍ los resultados en
/home/drexgen/Documents/ELEA/LLMADMIN-Elea/elea/specs/RESULTADOS-PRUEBA-MANUAL-UI.md
con: paso por paso qué probaste y qué viste exactamente (adjuntá o describí screenshots
si algo se ve raro), y al final una lista separada de "🔴 bugs encontrados" vs "🟢 todo
OK". No hace falta que arregles nada del código — solo documentar. La sesión principal
sigue desde ese archivo.
```

---

## Qué hago yo cuando termine

Cuando el usuario me avise que la otra sesión terminó, leo
`specs/RESULTADOS-PRUEBA-MANUAL-UI.md`, reviso los hallazgos, y:
- Si hay bugs reales → los reproduzco, los arreglo con test, commiteo y pusheo.
- Actualizo `VERIFICACION-043-044-pruebas.md` con los resultados reales (🟢/🟡/🔴) en
  P1, P3, P5 y branding.
- Si todo salió bien, lo dejo asentado como corrida en vivo confirmada por UI, no solo
  por API.
