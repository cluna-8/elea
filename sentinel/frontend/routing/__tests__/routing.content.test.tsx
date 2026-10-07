import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ContentRouting } from "../ContentRouting";
import { erroresDeRuta, mezclarFrases, normalizarRouter } from "../contentHelpers";

const CFG = {
  enabled: true, default_model: "modelo-a", timeout_seconds: 5, embedding_model: "bge-m3",
  routes: [{ name: "Código", description: "programar", target_model: "modelo-b", score_threshold: 0.5, tier: "premium",
    utterances: ["escribí una función"], target_ok: true }],
  default_model_ok: true, embedding_model_ok: true, config_error: false,
};
const MODELS = [
  { model_name: "modelo-a", provider: "openai", is_configured: true },
  { model_name: "modelo-b", provider: "openai", is_configured: true },
  { model_name: "auto", provider: "auto", is_configured: true },
  { model_name: "apagado", provider: "openai", is_configured: false },
];

function setup(role: string, over: Record<string, () => Response> = {}) {
  localStorage.setItem("sentinel_session_token", "t");
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role, email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const key = `${init?.method ?? "GET"} ${url}`;
    if (over[key]) return over[key]();
    if (key === "GET /api/v1/chat/router-config") return new Response(JSON.stringify(CFG), { status: 200 });
    if (key === "GET /api/v1/chat/models") return new Response(JSON.stringify(MODELS), { status: 200 });
    if (key === "PUT /api/v1/chat/router-config") return new Response(init!.body as string, { status: 200 });
    return new Response("{}", { status: 404 });
  }));
  return calls;
}

describe("helpers del ruteo por contenido", () => {
  it("normaliza una config parcial y valida rutas", () => {
    const n = normalizarRouter({});
    expect(n.routes).toEqual([]);
    expect(n.timeout_seconds).toBe(5);
    expect(Object.keys(erroresDeRuta({ name: "", target_model: "", score_threshold: 2, utterances: [] })).sort())
      .toEqual(["name", "target", "umbral", "utterances"]);
    expect(mezclarFrases(["Hola mundo"], ["hola  mundo".replace("  ", " "), "otra", "OTRA"])).toEqual(["otra"]);
  });
});

describe("ruteo por contenido", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("carga la config y los modelos reales (sin «auto» ni los no configurados)", async () => {
    setup("admin");
    render(<ContentRouting />);
    expect(await screen.findByText("Código")).toBeInTheDocument();
    const sel = screen.getByRole("combobox", { name: "Modelo por defecto" }) as HTMLSelectElement;
    expect(sel.value).toBe("modelo-a");
    expect(Array.from(sel.options).map(o => o.value)).toEqual(["", "modelo-a", "modelo-b"]);
  });

  it("guarda con PUT solo después de editar y avisa el resultado", async () => {
    const calls = setup("admin");
    render(<ContentRouting />);
    const guardar = await screen.findByRole("button", { name: "Guardar ruteo" });
    expect(guardar).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton", { name: /Timeout/ }), { target: { value: "8" } });
    expect(screen.getByText("Cambios sin guardar")).toBeInTheDocument();
    fireEvent.click(guardar);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Ruteo por contenido guardado/));
    const put = calls.find(c => c.init?.method === "PUT")!;
    const body = JSON.parse(String(put.init!.body));
    expect(body.timeout_seconds).toBe(8);
    expect(body).not.toHaveProperty("default_model_ok");
  });

  it("valida: ruta nueva incompleta bloquea el guardado y marca los campos", async () => {
    setup("admin");
    render(<ContentRouting />);
    await screen.findByText("Código");
    fireEvent.click(screen.getByRole("button", { name: "+ Agregar ruta" }));
    expect(await screen.findByText("El nombre es obligatorio.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar ruteo" })).toBeDisabled();
  });

  it("genera ejemplos con el modelo local y los mezcla sin duplicar", async () => {
    const calls = setup("admin", {
      "POST /api/v1/chat/router-config/generate-utterances": () =>
        new Response(JSON.stringify({ utterances: ["escribí una función", "corregí este bug"] }), { status: 200 }),
    });
    render(<ContentRouting />);
    fireEvent.click(await screen.findByRole("button", { name: /Código/ }));
    fireEvent.click(screen.getByRole("button", { name: /Calibración/ }));
    fireEvent.click(screen.getByRole("button", { name: "Generar ejemplos" }));
    expect(await screen.findByText("corregí este bug")).toBeInTheDocument();
    expect(screen.getAllByText("escribí una función")).toHaveLength(1);
    const sent = JSON.parse(String(calls.find(c => c.url.endsWith("generate-utterances"))!.init!.body));
    expect(sent).toMatchObject({ name: "Código", description: "programar" });
  });

  it("muestra el error de la generación tal cual lo manda el backend", async () => {
    setup("admin", {
      "POST /api/v1/chat/router-config/generate-utterances": () =>
        new Response(JSON.stringify({ detail: "no hay modelo local disponible" }), { status: 503 }),
    });
    render(<ContentRouting />);
    fireEvent.click(await screen.findByRole("button", { name: /Código/ }));
    fireEvent.click(screen.getByRole("button", { name: /Calibración/ }));
    fireEvent.click(screen.getByRole("button", { name: "Generar ejemplos" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/no hay modelo local disponible/);
  });

  it("rol sin permiso: solo lectura, sin guardar, agregar, eliminar ni generar", async () => {
    setup("compliance_officer");
    render(<ContentRouting />);
    fireEvent.click(await screen.findByRole("button", { name: /Código/ }));
    expect(screen.getByText(/modo consulta/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar ruteo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Agregar ruta" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Eliminar" })).toBeNull();
    expect(screen.getByRole("textbox", { name: /Nombre/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Calibración/ }));
    expect(screen.queryByRole("button", { name: "Generar ejemplos" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Agregar frase de ejemplo" })).toBeDisabled();
  });

  it("si la config no carga, ofrece reintentar", async () => {
    setup("admin", { "GET /api/v1/chat/router-config": () => new Response(JSON.stringify({ detail: "falló" }), { status: 500 }) });
    render(<ContentRouting />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
