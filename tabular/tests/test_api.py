"""Contrato 03 §3.2: auth interna, subida, consulta con Guardian simulado, errores con código."""
import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.llm import EngineError
from app.store import SpaceStore

TOKEN = "test-internal-token"
H = {"Authorization": f"Bearer {TOKEN}", "X-Hub-User-Id": "ana-id"}
CSV = b"depto,vendedor,monto\nVentas,ana,100\nVentas,luis,50\nMarketing,jo,300\n"


class FakeEngine:
    """Simula Guardian: primera llamada devuelve SQL, segunda la redacción."""

    def __init__(self, sql_replies, answer="Ventas suma 150 y Marketing 300."):
        self.sql_replies = list(sql_replies)
        self.answer = answer
        self.calls = []

    def chat(self, messages, *, acting_user_id, max_tokens=800, temperature=0.0):
        self.calls.append({"acting_user_id": acting_user_id, "system": messages[0]["content"][:40],
                           "last": messages[-1]["content"]})
        if "SQL de DuckDB" in messages[0]["content"]:
            reply = self.sql_replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply, "azure-gpt-4o-mini"
        return self.answer, "azure-gpt-4o-mini"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "internal_token", TOKEN)
    monkeypatch.setattr(main, "store", SpaceStore(str(tmp_path), sample_rows=2))
    return TestClient(main.app)


def _space_with_csv(client):
    assert client.post("/v1/spaces", json={"workspace_id": "ws-1"}, headers=H).status_code == 201
    r = client.post("/v1/spaces/ws-1/files", headers=H,
                    files={"file": ("ventas.csv", io.BytesIO(CSV), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def test_sin_token_401_y_sin_usuario_400(client):
    assert client.post("/v1/spaces", json={"workspace_id": "x"}).status_code == 401
    assert client.post("/v1/spaces", json={"workspace_id": "x"},
                       headers={"Authorization": "Bearer otro", "X-Hub-User-Id": "a"}).status_code == 401
    assert client.post("/v1/spaces", json={"workspace_id": "x"},
                       headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 400


def test_health_sin_auth(client):
    assert client.get("/health").status_code == 200


def test_flujo_completo(client, monkeypatch):
    fake = FakeEngine(["SELECT depto, SUM(monto) AS total FROM t1 GROUP BY depto ORDER BY depto"])
    monkeypatch.setattr(main, "engine", fake)
    entry = _space_with_csv(client)
    assert entry["tables"][0]["name"] == "f1_ventas"

    assert client.post("/v1/spaces", json={"workspace_id": "ws-1"}, headers=H).status_code == 409

    r = client.post("/v1/spaces/ws-1/query", json={"question": "total por depto"}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == [{"depto": "Marketing", "total": 300}, {"depto": "Ventas", "total": 150}]
    assert body["columns"] == ["depto", "total"]
    assert "LIMIT" in body["sql"]
    assert body["answer"].startswith("Ventas suma")
    assert body["model_used"] == "azure-gpt-4o-mini"
    # La identidad de la persona viaja a Guardian en TODAS las llamadas (FR-022).
    assert {c["acting_user_id"] for c in fake.calls} == {"ana-id"}
    assert len(fake.calls) == 2

    files = client.get("/v1/spaces/ws-1/files", headers=H).json()["files"]
    assert files[0]["file_id"] == entry["file_id"]
    assert client.delete(f"/v1/spaces/ws-1/files/{entry['file_id']}", headers=H).status_code == 200
    r = client.post("/v1/spaces/ws-1/query", json={"question": "x"}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_files"


def test_sql_destructivo_se_rechaza_tras_un_reintento(client, monkeypatch):
    fake = FakeEngine(["DROP TABLE f1_ventas", "DELETE FROM f1_ventas"])
    monkeypatch.setattr(main, "engine", fake)
    _space_with_csv(client)
    r = client.post("/v1/spaces/ws-1/query", json={"question": "borrá todo"}, headers=H)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "unsafe_sql"
    assert "rechazada" in fake.calls[1]["last"]  # el reintento llevó el motivo
    # nada se ejecutó
    assert client.get("/v1/spaces/ws-1/files", headers=H).json()["files"][0]["tables"][0]["rows"] == 3


def test_sql_con_error_se_corrige_en_el_reintento(client, monkeypatch):
    fake = FakeEngine(["SELECT columna_que_no_existe FROM f1_ventas",
                       "SELECT COUNT(*) AS n FROM f1_ventas"])
    monkeypatch.setattr(main, "engine", fake)
    _space_with_csv(client)
    r = client.post("/v1/spaces/ws-1/query", json={"question": "cuántas filas"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [{"n": 3}]
    assert "falló" in fake.calls[1]["last"]


def test_no_sql(client, monkeypatch):
    monkeypatch.setattr(main, "engine", FakeEngine(["NO_SQL"]))
    _space_with_csv(client)
    r = client.post("/v1/spaces/ws-1/query", json={"question": "qué opinás del clima"}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_answerable"


@pytest.mark.parametrize("status", [400, 401, 402])
def test_errores_del_engine_se_reenvian_con_codigo(client, monkeypatch, status):
    monkeypatch.setattr(main, "engine", FakeEngine([EngineError(status, "x")]))
    _space_with_csv(client)
    r = client.post("/v1/spaces/ws-1/query", json={"question": "x"}, headers=H)
    assert r.status_code == 502
    assert r.json()["detail"] == {"code": "engine_error", "status": status}


def test_formato_y_tamano(client, monkeypatch):
    monkeypatch.setattr(main.settings, "max_file_mb", 1)
    assert client.post("/v1/spaces", json={"workspace_id": "ws-1"}, headers=H).status_code == 201
    r = client.post("/v1/spaces/ws-1/files", headers=H,
                    files={"file": ("x.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    assert r.status_code == 415
    big = b"a,b\n" + b"1,2\n" * 300000
    r = client.post("/v1/spaces/ws-1/files", headers=H, files={"file": ("big.csv", io.BytesIO(big), "text/csv")})
    assert r.status_code == 413
    r = client.post("/v1/spaces/nope/files", headers=H, files={"file": ("a.csv", io.BytesIO(CSV), "text/csv")})
    assert r.status_code == 404


def test_xlsx_dos_hojas(client, monkeypatch):
    monkeypatch.setattr(main, "engine", FakeEngine(["SELECT COUNT(*) AS n FROM t1"]))
    assert client.post("/v1/spaces", json={"workspace_id": "ws-1"}, headers=H).status_code == 201
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"x": [1, 2, 3]}).to_excel(w, sheet_name="Hoja1", index=False)
        pd.DataFrame({"y": ["a"]}).to_excel(w, sheet_name="Hoja2", index=False)
    r = client.post("/v1/spaces/ws-1/files", headers=H,
                    files={"file": ("libro.xlsx", io.BytesIO(buf.getvalue()),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    assert [t["name"] for t in r.json()["tables"]] == ["f1_libro_hoja1", "f1_libro_hoja2"]
    r = client.post("/v1/spaces/ws-1/query", json={"question": "cuántas"}, headers=H)
    assert r.status_code == 200 and r.json()["rows"] == [{"n": 3}]


def test_sql_no_parseable_va_por_fallback_y_ejecuta(client, monkeypatch):
    # sqlglot no interpreta esto (paréntesis raro que DuckDB sí acepta como subconsulta escalar
    # con alias implícito) → validación conservadora → DuckDB lo ejecuta en solo lectura.
    fake = FakeEngine(["SELECT (SELECT COUNT(*) FROM t1) AS n, ((1)) AS uno"])
    monkeypatch.setattr(main, "engine", fake)
    _space_with_csv(client)
    r = client.post("/v1/spaces/ws-1/query", json={"question": "cuántas"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [{"n": 3, "uno": 1}]
