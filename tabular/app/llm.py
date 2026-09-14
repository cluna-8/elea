"""Cliente hacia Guardian (API OpenAI en `engine:4000/v1`) — spec 050 FR-022/024, contrato 03 §3.2.

tabular NUNCA habla con un proveedor: solo con el engine, con su llave `svc.tabular` y la
cabecera `X-Guardian-Acting-User` con la persona real (el engine la honra si la llave tiene
`can_act_on_behalf`). Errores del engine se reenvían con su código para que el Hub muestre
copy neutro: 400 = bloqueo de política, 401 = llave inválida, 402 = presupuesto agotado.
"""
from __future__ import annotations

import json

import httpx


class EngineError(RuntimeError):
    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"engine {status}: {detail}")
        self.status = status
        self.detail = detail


class EngineClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def _post(self, payload: dict) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if getattr(self, "_acting", None):
            headers["X-Guardian-Acting-User"] = self._acting
        try:
            return httpx.post(f"{self.base_url}/chat/completions", headers=headers,
                              json=payload, timeout=self.timeout_s)
        except httpx.RequestError as e:
            raise EngineError(503, f"engine no alcanzable: {e.__class__.__name__}") from e

    def chat(self, messages: list[dict], *, acting_user_id: str | None, max_tokens: int = 800,
             temperature: float = 0.0) -> tuple[str, str]:
        """Devuelve (texto, modelo_usado). Lanza EngineError con el código del engine."""
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                   "temperature": temperature, "stream": False}
        self._acting = acting_user_id
        r = self._post(payload)
        # Algunos deployments (visto con azure-gpt-5.1-chat) rechazan `temperature` distinta de
        # la default con 400 "Unsupported value" — se reintenta una vez sin el parámetro.
        if r.status_code == 400 and "temperature" in r.text and "Unsupported" in r.text:
            payload.pop("temperature", None)
            r = self._post(payload)
        if r.status_code >= 400:
            detail = ""
            try:
                body = r.json()
                detail = body.get("detail") or body.get("error", {}).get("message") or json.dumps(body)[:300]
            except ValueError:
                detail = r.text[:300]
            raise EngineError(r.status_code, str(detail))
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise EngineError(502, "respuesta del engine sin contenido") from e
        return text.strip(), data.get("model") or self.model


SQL_SYSTEM = (
    "Sos un analista de datos experto en SQL de DuckDB. Traducís preguntas de negocio a UNA consulta.\n"
    "Reglas estrictas:\n"
    "1. Respondé ÚNICAMENTE con una sola sentencia SELECT (puede empezar con WITH). Sin explicaciones, "
    "sin comentarios, sin markdown, sin punto y coma final.\n"
    "2. Usá solo las tablas y columnas del esquema, con el nombre exacto en minúsculas y guión bajo. "
    "El tipo que figura después de los dos puntos es informativo: NUNCA lo escribas en el SQL.\n"
    "3. Si una tabla no tiene la columna que necesitás (por ejemplo el nombre de un producto), "
    "buscala en otra tabla y uní por la clave en común (el esquema lista las columnas en común). "
    "Calificá cada columna con el alias de su tabla. Si la otra tabla tiene varias filas por clave "
    "(versiones, períodos), reducila primero con SELECT DISTINCT o GROUP BY para no duplicar.\n"
    "4. Si la pregunta tiene dos partes, resolvé las dos en la misma consulta (CTEs o subconsultas). "
    "Si una parte no se puede, resolvé la principal.\n"
    "5. Para buscar un texto (nombre de producto, familia, estado) usá ILIKE con comodines, "
    "porque la escritura de la persona puede no coincidir exactamente.\n"
    "6. Períodos tipo '2025-03' son VARCHAR; las columnas *_date o de fecha son TIMESTAMP: "
    "usá CAST('2027-01-01' AS TIMESTAMP) o funciones de fecha de DuckDB al comparar.\n"
    "7. Nunca escribas, borres ni modifiques datos. Nunca leas archivos ni recursos externos.\n"
    "8. Respondé exactamente NO_SQL solo en dos casos: (a) la pregunta no tiene relación con estas tablas; "
    "(b) pide un JUICIO sobre los valores que ninguna columna contiene, por ejemplo '¿hay nombres de "
    "personas?' o '¿qué descripción es negativa?' — buscar la palabra 'persona' con ILIKE daría una "
    "respuesta engañosa. En cambio, 'contame todo sobre IOT', 'qué hay de COTEC', 'buscá X' SÍ son SQL: "
    "devolvé las filas cuyas columnas de texto contengan ese término (ILIKE '%término%'), con todas las "
    "columnas, y si hay varias tablas buscá en cada una.\n"
    "11. Si la pregunta es sobre la CONVERSACIÓN misma y no sobre los datos (por ejemplo 'resumime lo que "
    "hablamos', '¿qué te pregunté antes?', 'repetime la respuesta anterior'), NO escribas SQL: respondé "
    "con la palabra CHAT: seguida de la respuesta en español, usando el resumen y los turnos anteriores.\n"
    "10. Para buscar un término en VARIAS tablas con columnas distintas, usá UNION ALL BY NAME "
    "(DuckDB alinea por nombre de columna y rellena con NULL las que faltan): "
    "SELECT 'Nombre legible' AS hoja, * FROM t1 WHERE col ILIKE '%x%' UNION ALL BY NAME "
    "SELECT 'Otro nombre' AS hoja, * FROM t2 WHERE col ILIKE '%x%'. Como valor literal de 'hoja' "
    "usá el nombre legible que da el esquema, nunca t1/t2. Mantené la consulta compacta.\n"
    "9. Si en el esquema o en la pregunta ves un token entre corchetes con el formato [TIPO_numero_codigo] "
    "(por ejemplo [PERSON_0_a03c] o [ORGANIZATION_1_9f2e]), es un dato protegido: copialo EXACTO, con los "
    "corchetes, letra por letra, como valor de texto entre comillas simples. NUNCA lo modifiques ni lo "
    "uses como nombre de tabla o columna."
)

ANSWER_SYSTEM = (
    "Sos un analista de datos. Redactás en español rioplatense, breve y directo, una lectura de los "
    "resultados de una consulta. Reglas estrictas:\n"
    "1. Usá SOLO las cifras que aparecen en los resultados, copiadas tal cual (podés agregar separadores "
    "de miles, nada más). Está PROHIBIDO inventar, estimar o corregir un número.\n"
    "2. No juzgues si un valor es válido o no: los resultados son correctos por definición.\n"
    "3. Si hay más filas que las mostradas, decí cuántas hay en total y resumí las primeras.\n"
    "4. Si la tabla está vacía, decí que no hubo resultados para ese criterio.\n"
    "5. No repitas la tabla entera: la persona ya la ve. Resumí lo importante en pocas líneas."
)


SUMMARY_SYSTEM = (
    "Resumís, en español rioplatense y en no más de 120 palabras, una conversación entre una persona "
    "y un analista de datos sobre unas planillas. Conservá: qué quiso saber la persona, las cifras y "
    "conclusiones que ya obtuvo (copiadas tal cual), y sus preferencias (por ejemplo, cómo quiere ver "
    "los datos). Si te dan un resumen previo, integralo: el resultado es UN solo resumen acumulado. "
    "Sin encabezados, sin listas, sin comentarios sobre el resumen mismo."
)


def summary_messages(previous_summary: str | None, turns: list[dict]) -> list[dict]:
    body = ""
    if previous_summary:
        body += f"Resumen previo:\n{previous_summary}\n\n"
    body += "Turnos nuevos a integrar:\n" + "\n".join(
        f"- Pregunta: {t.get('question', '')}\n  Respuesta: {t.get('answer', '')}" for t in turns)
    return [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": body}]


def sql_messages(schema_text: str, question: str, history: list[dict] | None,
                 error_feedback: str | None = None, common_keys: dict[str, list[str]] | None = None,
                 summary: str | None = None) -> list[dict]:
    schema = schema_text
    if common_keys:
        schema += "\n\nColumnas en común entre tablas (claves para JOIN):\n" + "\n".join(
            f"  - {col}: {', '.join(tabs)}" for col, tabs in common_keys.items())
    msgs = [{"role": "system", "content": SQL_SYSTEM},
            {"role": "user", "content": f"Esquema:\n{schema}"}]
    if summary:
        msgs.append({"role": "user", "content": f"Resumen de la conversación anterior con esta persona:\n{summary}"})
    for h in (history or [])[-5:]:
        if h.get("question"):
            msgs.append({"role": "user", "content": h["question"]})
        if h.get("answer"):
            msgs.append({"role": "assistant", "content": h["answer"]})
    msgs.append({"role": "user", "content": f"Pregunta: {question}"})
    if error_feedback:
        msgs.append({"role": "user", "content":
                     f"La consulta anterior falló: {error_feedback}\nCorregila y devolvé solo el SELECT."})
    return msgs


def answer_messages(question: str, sql: str, columns: list[str], rows: list[dict],
                    total_rows: int, table_labels: dict[str, str] | None = None) -> list[dict]:
    table = json.dumps(rows, ensure_ascii=False)
    note = f" (mostrando {len(rows)} de {total_rows} filas)" if total_rows > len(rows) else ""
    labels = ""
    if table_labels:
        labels = "\nNombres de las tablas para la persona (usá estos, nunca t1/t2 ni f1_...): " + \
                 "; ".join(f"{k} = {v}" for k, v in table_labels.items())
    return [{"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content":
             f"Pregunta: {question}\nSQL ejecutado: {sql}\nColumnas: {columns}{labels}\n"
             f"Total de filas del resultado: {total_rows} (usá este número si mencionás cuántos hay)\n"
             f"Resultados{note}: {table}"}]
