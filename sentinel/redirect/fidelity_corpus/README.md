# Corpus de la prueba de fidelidad

Conversaciones **sintéticas** con la forma de pedido de cada herramienta cliente, que la prueba
de fidelidad (`sentinel/redirect/fidelity.py`, spec 068 FR-031) reproduce contra un destino.
Un archivo por herramienta: `claude_code.json`, `claude_desktop.json`, `codex.json`,
`openai_generic.json` (los mismos nombres que `kits.TOOLS`).

> No es el corpus de tramas grabadas de la 068 (`sentinel/tests/fixtures/harness_corpus/`, T023):
> aquel compara el tráfico con la política apagada y exige cuerpo, cabeceras y eventos idénticos;
> este mide si un destino traducido sostiene cada función de la herramienta.

## Formato

```json
{
  "corpus_version": "2026.10.1",
  "synthetic": true,
  "tool": "claude_code",
  "face": "claude",
  "recorded_with": "forma de pedido de la herramienta, texto sintético escrito a mano",
  "cases": [
    {"capability": "tools", "name": "llamada-de-herramienta",
     "request": { "...cuerpo en la forma NATIVA de la cara..." },
     "expect": {"tool": "read_file"}}
  ]
}
```

- **Una capacidad por caso**, con las cinco de `fidelity.CAPABILITIES`: `conversation`,
  `tools`, `long_stream`, `errors`, `context`. `name` es único dentro del archivo: es la clave con
  la que se comparan corridas.
- `request` está en la forma de la cara (mensajes de Claude, Responses de Codex, chat genérico);
  la prueba solo le pone el `model` del destino. Las claves permitidas están en
  `fidelity.ALLOWED_BODY_KEYS`.
- `expect` según la capacidad: `tool` (nombre de la herramienta que debe llamar), `min_events` y
  `min_chars` (streaming largo), `error_class` (lista de clases aceptables; el caso `errors`
  manda un pedido inválido a propósito y pasa solo si el destino lo rechaza con un error que la
  herramienta entiende).
- Caso `context`: `needle` (el dato a recuperar) y `fill_ratio` (fracción de la ventana del
  destino a rellenar; tope duro de 40 000 caracteres). El cuerpo lleva `{{CONTEXT}}`, que se
  reemplaza por texto de relleno fijo con el dato escondido.

## Reglas de contenido

- **Sin datos reales**: todo se escribe a mano. Jamás pegar una conversación de un usuario, ni
  siquiera «anonimizada». Los tests rechazan correos y números de aspecto personal.
- Sin credenciales, sin URLs internas, sin nombres del motor ni marca del fabricante del producto.
- Texto en castellano neutro, corto: cada caso cuesta dinero del presupuesto de la prueba.

## Re-ejecución al salir una versión nueva de una herramienta

Objetivo (US5, escenario 4): ver las regresiones **antes** de que lleguen a los usuarios.

1. **Instalar la versión nueva** en una máquina de prueba y mirar qué cambió en la forma de sus
   pedidos (campos nuevos, bloques de contenido, herramientas, cabeceras). Si no cambió nada que
   toque estos casos, seguir en el paso 3.
2. **Actualizar el corpus** solo si la forma cambió: editar el `request` del caso afectado en la
   forma nueva, sin copiar tráfico real, y subir `corpus_version` (año.mes.n). Un cambio de
   corpus invalida la comparación con corridas anteriores: la primera corrida con el corpus nuevo
   no tiene contra qué compararse.
3. **Correr la prueba** para cada destino que esté mapeado a la cara de esa herramienta (pestaña
   Fidelidad, o `POST /api/v1/redirect/fidelity-runs` con `destination_id`, `tool` y
   `tool_version` = la versión instalada). Declarar siempre la versión: es lo que identifica la
   corrida en el historial.
4. **Leer el informe**. La sección «Regresión respecto de la corrida anterior» lista lo que
   pasaba con la versión previa y ahora no (`regressions` en la respuesta). Un veredicto
   `incompleto` significa que se agotó `REDIRECT_FIDELITY_BUDGET_USD`: subirlo y repetir; no se
   acepta como apto.
5. **Decidir antes de desplegar la versión a los usuarios**: con regresión o veredicto `no_apto`,
   no ampliar el alcance de la regla ni repartir un kit con esa versión; corregir el perfil de
   capacidades del destino, cambiar el destino de la regla, o fijar la versión anterior de la
   herramienta (el kit no la fija: eso es de la gestión de dispositivos).
6. **Dejar constancia**: las corridas ya quedan guardadas (`GET /api/v1/redirect/fidelity-runs`).
   Anotar en el PR o runbook de la actualización qué versión se probó y contra qué destinos.

Verificación del propio corpus (sin red): `PYTHONPATH=backend backend/.venv/bin/python -m pytest
sentinel/tests/unit/test_redirect_fidelity.py`.
