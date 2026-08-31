# Tasks: Cobertura completa de los 6 puntos del cliente Elea

Orden sugerido: de más chico/rápido a más grande, así se puede mostrar avance seguido.

## Fase 1 — PPTX (chico, mismo patrón que xlsx/pdf ya resueltos)

- [ ] **T010** Agregar `python-pptx` a `client/Dockerfile` (mismo criterio que `pypdf`,
  agregado 31-ago).
- [ ] **T011** Manejador `.pptx` en `client/extract_text.py`: iterar diapositivas,
  extraer texto de cada `shape.text_frame`, con el número de diapositiva como referencia
  (para que las citas del RAG digan "Diapositiva 3", no solo el nombre del archivo).
- [ ] **T012** Probar con un `.pptx` real (con algún dato personal en una diapositiva) —
  mismo patrón de prueba que xlsx/csv/docx/pdf: subir, confirmar enmascarado, preguntar
  contenido específico, confirmar que la respuesta cita la fuente correcta.

## Fase 2 — Formateo de respuesta (depende de la decisión de diseño de spec.md US2)

- [ ] **T020** Decidir (a) selector visible de formato vs (b) solo lenguaje natural —
  confirmar con el usuario antes de codear, no asumir.
- [ ] **T021** (si es (a)) Agregar el selector a `public/index.html` + un parámetro
  `formato` en `/api/chat` que se traduzca en una instrucción de sistema agregada al
  pedido antes de mandarlo.

## Fase 3 — Presupuesto por rol (UX sobre lo que ya existe)

- [ ] **T030** Documentar en `client/README.md` / `elea-installer/README.md` el flujo
  exacto: crear un `Group` con nombre del rol → `POST /budgets` con `group_id` → los
  usuarios de ese Group heredan el presupuesto.
- [ ] **T031** (opcional) Agregar un `create-role-budget.sh` al instalador, mismo patrón
  que `create-tester.sh`, para no tener que armar el POST a mano.

## Fase 4 — Generación de documentos (grande — investigar antes de diseñar)

- [ ] **T040** Investigar el "Document Generation Agent" de AnythingLLM (modo `@agent`)
  contra la instancia real — confirmar si alcanza para pptx/docx/pdf/xlsx antes de
  construir algo propio.
- [ ] **T041** Si no alcanza: evaluar alternativas (librerías de generación directa desde
  el cliente, o un servicio dedicado) — spec aparte, esto es más grande que un ajuste.

## Fase 5 — Cruces CSV/Excel exactos (la más grande — servicio nuevo)

- [ ] **T050** Retomar la evaluación de DB-GPT del laboratorio previo (`HARNES-PRUEBAS`,
  específicamente `reports/06_resumen_sesion_marketplace_punto4_y_puertos.md` si sigue
  existiendo) — confirmar si sigue siendo la mejor opción.
- [ ] **T051** Diseñar cómo se integra con el cliente actual: ¿otro botón "Análisis
  exacto" separado del chat RAG? ¿Un tipo de workspace distinto? Requiere spec propia,
  no es una tarea chica.
