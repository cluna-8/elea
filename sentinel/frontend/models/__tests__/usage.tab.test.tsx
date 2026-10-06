import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { UsageTab } from "../UsageTab";

const REPORT = {
  from: "2026-09-02", to: "2026-10-01", group: "model",
  data: [
    { key: "m1", name: "modelo-barato", requests: 10, prompt_tokens: 1000, completion_tokens: 500, cost_usd: 0.25, latency_avg_ms: 120, latency_p95_ms: 300, billing: "measured" },
    { key: "m2", name: "modelo-caro", requests: 4, prompt_tokens: 2000, completion_tokens: 1000, cost_usd: 1.5, latency_avg_ms: 900, latency_p95_ms: 2000, billing: "measured" },
    { key: "m3", name: "modelo-plano", requests: 7, prompt_tokens: 10, completion_tokens: 10, cost_usd: 0, latency_avg_ms: null, latency_p95_ms: null, billing: "flat" },
  ],
  totals: { requests: 21, prompt_tokens: 3010, completion_tokens: 1510, cost_usd: 1.75 },
};

function mock(handler?: (url: string) => Response) {
  const urls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    return handler ? handler(url) : new Response(JSON.stringify(REPORT), { status: 200 });
  }));
  return urls;
}
const names = () => screen.getAllByRole("row").slice(1).map(r => within(r).getAllByRole("cell")[0].textContent);

describe("pestaña Consumo", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("pide 30 días por modelo, muestra totales y ordena por costo descendente", async () => {
    const urls = mock();
    render(<UsageTab />);
    expect(await screen.findByText("modelo-caro")).toBeInTheDocument();
    expect(urls[0]).toMatch(/^\/api\/v1\/catalog\/usage\?/);
    expect(urls[0]).toContain("group=model");
    expect(screen.getByText("21")).toBeInTheDocument();
    expect(names()).toEqual(["modelo-caro", "modelo-barato", "modelo-plano"]);
  });

  it("la tarifa plana se marca distinta del costo medido", async () => {
    mock();
    render(<UsageTab />);
    await screen.findByText("modelo-plano");
    const fila = screen.getByText("modelo-plano").closest("tr")!;
    expect(within(fila).getByText("Tarifa plana")).toBeInTheDocument();
    expect(within(screen.getByText("modelo-caro").closest("tr")!).queryByText("Tarifa plana")).toBeNull();
  });

  it("cambia el período y el agrupado y vuelve a pedir", async () => {
    const urls = mock();
    render(<UsageTab />);
    await screen.findByText("modelo-caro");
    fireEvent.click(screen.getByRole("button", { name: "90 días" }));
    await waitFor(() => expect(urls.length).toBe(2));
    fireEvent.click(screen.getByRole("button", { name: "Por destino" }));
    await waitFor(() => expect(urls[2]).toContain("group=destination"));
    expect(screen.getByRole("button", { name: "Por destino" })).toHaveAttribute("aria-pressed", "true");
  });

  it("ordena al tocar el encabezado", async () => {
    mock();
    render(<UsageTab />);
    await screen.findByText("modelo-caro");
    fireEvent.click(screen.getByRole("button", { name: /^Pedidos/ }));
    expect(names()[0]).toBe("modelo-barato");
  });

  it("estado vacío", async () => {
    mock(() => new Response(JSON.stringify({ ...REPORT, data: [], totals: { requests: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 } }), { status: 200 }));
    render(<UsageTab />);
    expect(await screen.findByText(/Todavía no hay consumo/)).toBeInTheDocument();
  });

  it("error legible con reintento, sin volcado técnico", async () => {
    mock(() => new Response(JSON.stringify({}), { status: 500 }));
    render(<UsageTab />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/El servidor tuvo un problema/);
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("nunca muestra contenido de pedidos", async () => {
    mock();
    render(<UsageTab />);
    await screen.findByText("modelo-caro");
    expect(screen.getByText(/nunca se muestra el contenido/)).toBeInTheDocument();
  });
});
