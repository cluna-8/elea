"""Spec 051: hilos y turnos por espacio (history.sqlite), aislamiento por persona, resumen de
conversaciones largas, turnos marcados al borrar una planilla, consulta con thread_key."""
import io

from fastapi.testclient import TestClient

from app import main
from app.history import History
from app.store import SpaceStore

TOKEN = "test-internal-token"
ANA = {"Authorization": f"Bearer {TOKEN}", "X-Hub-User-Id": "ana-id"}
LUIS = {"Authorization": f"Bearer {TOKEN}", "X-Hub-User-Id": "luis-id"}
CSV = b"depto,vendedor,monto\nVentas,ana,100\nVentas,luis,50\nMarketing,jo,300\n"


class FakeEngine:
    def __init__(self):
        self.calls = []

    def chat(self, messages, *, acting_user_id, max_tokens=800, temperature=0.0):
        self.calls.append(messages)
        sys = messages[0]["content"]
        if sys.startswith("Resumís"):
            return "RESUMEN: la persona pregunta totales por depto.", "m"
        if "resumime" in messages[-1]["content"].lower():
            return "CHAT: Preguntaste totales por depto.", "m"
        if "SQL de DuckDB" in sys:
            return 'SELECT depto, SUM(monto) AS total FROM t1 GROUP BY depto ORDER BY depto', "m"
        return "Ventas suma 150 y Marketing 300.", "m"


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "internal_token", TOKEN)
    monkeypatch.setattr(main, "store", SpaceStore(str(tmp_path), sample_rows=2))
    monkeypatch.setattr(main, "history_store", History(lambda ws: main.store._dir(ws), window=2, summary_every=3))
    fake = FakeEngine()
    monkeypatch.setattr(main, "engine", fake)
    c = TestClient(main.app)
    assert c.post("/v1/spaces", json={"workspace_id": "ws-1"}, headers=ANA).status_code == 201
    assert c.post("/v1/spaces/ws-1/files", headers=ANA,
                  files={"file": ("ventas.csv", io.BytesIO(CSV), "text/csv")}).status_code == 201
    return c, fake


def test_hilos_crear_listar_renombrar_borrar_y_aislamiento(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    r = c.post("/v1/spaces/ws-1/threads", json={"key": "ana-1", "title": "Ventas Q1"}, headers=ANA)
    assert r.status_code == 201 and r.json()["turns"] == 0
    # idempotente para la misma persona
    assert c.post("/v1/spaces/ws-1/threads", json={"key": "ana-1"}, headers=ANA).status_code == 201
    # otra persona no puede tomar la misma key, ni verla, ni borrarla
    assert c.post("/v1/spaces/ws-1/threads", json={"key": "ana-1"}, headers=LUIS).status_code == 403
    assert c.get("/v1/spaces/ws-1/threads", headers=LUIS).json()["threads"] == []
    assert c.get("/v1/spaces/ws-1/threads/ana-1/turns", headers=LUIS).status_code == 403
    assert c.delete("/v1/spaces/ws-1/threads/ana-1", headers=LUIS).status_code == 403
    assert c.patch("/v1/spaces/ws-1/threads/ana-1", json={"title": "Otro"}, headers=ANA).json()["title"] == "Otro"
    assert [t["key"] for t in c.get("/v1/spaces/ws-1/threads", headers=ANA).json()["threads"]] == ["ana-1"]
    assert c.delete("/v1/spaces/ws-1/threads/ana-1", headers=ANA).status_code == 200
    assert c.get("/v1/spaces/ws-1/threads/ana-1/turns", headers=ANA).status_code == 404
    assert c.post("/v1/spaces/ws-1/threads", json={"key": "mal clave!"}, headers=ANA).status_code == 422


def test_query_con_thread_guarda_turno_y_usa_contexto_del_hilo(tmp_path, monkeypatch):
    c, fake = _client(tmp_path, monkeypatch)
    r = c.post("/v1/spaces/ws-1/query", json={"question": "¿Total por depto?", "thread_key": "ana-1"}, headers=ANA)
    assert r.status_code == 200, r.text
    assert r.json()["turn_id"] == 1
    turns = c.get("/v1/spaces/ws-1/threads/ana-1/turns", headers=ANA).json()["turns"]
    assert len(turns) == 1 and turns[0]["question"] == "¿Total por depto?" and turns[0]["rows"] and turns[0]["sql"]
    assert turns[0]["stale"] is False
    # segunda pregunta sin `history`: el motor manda el turno anterior como contexto
    c.post("/v1/spaces/ws-1/query", json={"question": "¿Y solo Ventas?", "thread_key": "ana-1"}, headers=ANA)
    sql_call = [m for m in fake.calls if "SQL de DuckDB" in m[0]["content"]][-1]
    assert any(m["role"] == "user" and m["content"] == "¿Total por depto?" for m in sql_call)
    # turno puntual (lo usa el Hub para armar una presentación desde el historial)
    t = c.get("/v1/spaces/ws-1/threads/ana-1/turns/1", headers=ANA).json()
    assert t["columns"] == ["depto", "total"]
    # sin thread_key todo sigue igual que antes (compatibilidad)
    r = c.post("/v1/spaces/ws-1/query", json={"question": "¿Total?"}, headers=ANA)
    assert r.status_code == 200 and r.json()["turn_id"] is None


def test_resumen_de_conversacion_larga(tmp_path, monkeypatch):
    c, fake = _client(tmp_path, monkeypatch)   # window=2, summary_every=3
    for i in range(5):
        assert c.post("/v1/spaces/ws-1/query", json={"question": f"pregunta {i}", "thread_key": "ana-1"},
                      headers=ANA).status_code == 200
    # con 5 turnos: 3 viejos (fuera de la ventana de 2) → se resumieron en UNA llamada
    summaries = [m for m in fake.calls if m[0]["content"].startswith("Resumís")]
    assert len(summaries) == 1 and "pregunta 0" in summaries[0][1]["content"]
    # la pregunta siguiente lleva el resumen + últimos 2 turnos, no los 5
    c.post("/v1/spaces/ws-1/query", json={"question": "¿qué hablamos?", "thread_key": "ana-1"}, headers=ANA)
    sql_call = [m for m in fake.calls if "SQL de DuckDB" in m[0]["content"]][-1]
    texts = [m["content"] for m in sql_call]
    assert any("RESUMEN: la persona" in t for t in texts)
    assert "pregunta 4" in texts and "pregunta 3" in texts and "pregunta 0" not in texts


def test_borrar_planilla_marca_turnos(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    c.post("/v1/spaces/ws-1/query", json={"question": "¿Total?", "thread_key": "ana-1"}, headers=ANA)
    fid = c.get("/v1/spaces/ws-1/files", headers=ANA).json()["files"][0]["file_id"]
    r = c.delete(f"/v1/spaces/ws-1/files/{fid}", headers=ANA)
    assert r.status_code == 200 and r.json()["stale_turns"] == 1
    assert c.get("/v1/spaces/ws-1/threads/ana-1/turns", headers=ANA).json()["turns"][0]["stale"] is True


def test_pregunta_sobre_la_conversacion_responde_sin_sql(tmp_path, monkeypatch):
    c, fake = _client(tmp_path, monkeypatch)
    c.post("/v1/spaces/ws-1/query", json={"question": "¿Total?", "thread_key": "ana-1"}, headers=ANA)
    r = c.post("/v1/spaces/ws-1/query", json={"question": "Resumime lo que hablamos", "thread_key": "ana-1"}, headers=ANA)
    assert r.status_code == 200 and r.json()["sql"] is None and r.json()["answer"] == "Preguntaste totales por depto."
    assert r.json()["turn_id"] == 2
    turns = c.get("/v1/spaces/ws-1/threads/ana-1/turns", headers=ANA).json()["turns"]
    assert turns[-1]["sql"] is None and turns[-1]["answer"].startswith("Preguntaste")
