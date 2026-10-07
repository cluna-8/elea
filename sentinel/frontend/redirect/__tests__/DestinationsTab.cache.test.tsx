// 057 T077 (FR-043, FR-044, FR-046): la pestaña «Destinos» muestra y edita lo que el destino declara sobre la caché del proveedor
// (casillas «marcas de caché» y «afinidad de sesión», precio de lectura y escritura de caché) y el aprovechamiento por destino.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DestinationsTab } from "../DestinationsTab";
import { permissionsFor, type Destination } from "../helpers";

const patchEntry = vi.fn();
vi.mock("../../catalog/api", () => ({ catalogApi: { patchEntry: (...a: unknown[]) => patchEntry(...a) } }));

const BASE: Destination = {
  id: "d-1", level: "tenant", tenant_id: "t", name: "GLM UE", provider: "openrouter", real_model: "glm-5.2",
  protocol_family: "openai_chat", inference_jurisdiction: "DE", entity_jurisdiction: "DE", blocked_by_default: false,
  enabled_at: null, enable_reason: null, has_credential: true, api_base: null, status: "active",
  price_override: { input_per_mtok: 0.6, output_per_mtok: 2.2, cache_read_per_mtok: 0.11, cache_write_per_mtok: 0.75 },
  capability_profile: { cache_control: true, session_affinity: false, thinking: true },
} as Destination;
const SIN_CACHE: Destination = {
  ...BASE, id: "d-2", name: "Qwen UE", provider: "openai_compatible",
  price_override: { input_per_mtok: 0.3, output_per_mtok: 1.1 }, capability_profile: {},
} as Destination;

const ADMIN = permissionsFor("tenant_admin");
const LECTOR = permissionsFor("compliance_officer");
const noUtil = () => Promise.resolve({});

beforeEach(() => { patchEntry.mockReset(); patchEntry.mockResolvedValue({}); });
afterEach(() => vi.restoreAllMocks());

function fila(nombre: string) {
  return screen.getByText(nombre).closest("tr") as HTMLElement;
}

describe("DestinationsTab · caché del proveedor", () => {
  it("muestra las casillas según lo declarado y el precio de lectura y escritura de caché", async () => {
    render(<DestinationsTab perms={ADMIN} destinations={[BASE]} loadUtilization={noUtil} />);
    const row = within(fila("GLM UE"));
    expect((row.getByLabelText("Marcas de caché") as HTMLInputElement).checked).toBe(true);
    expect((row.getByLabelText("Afinidad de sesión") as HTMLInputElement).checked).toBe(false);
    expect(row.getByText(/caché: lectura 0,11 \/ escritura 0,75/i)).toBeTruthy();
  });

  it("sin declarar, la afinidad de sesión viene encendida solo en OpenRouter", () => {
    render(<DestinationsTab perms={ADMIN} destinations={[{ ...BASE, capability_profile: {} } as Destination, SIN_CACHE]}
      loadUtilization={noUtil} />);
    expect((within(fila("GLM UE")).getByLabelText("Afinidad de sesión") as HTMLInputElement).checked).toBe(true);
    expect((within(fila("Qwen UE")).getByLabelText("Afinidad de sesión") as HTMLInputElement).checked).toBe(false);
  });

  it("avisa que sin precio de caché se cobra a precio de entrada", () => {
    render(<DestinationsTab perms={ADMIN} destinations={[SIN_CACHE]} loadUtilization={noUtil} />);
    expect(within(fila("Qwen UE")).getByText(/sin precio de caché/i)).toBeTruthy();
  });

  it("el aprovechamiento se pide a demanda: sin pedirlo no se llama a los costos ni se muestra nada", () => {
    const load = vi.fn(noUtil);
    render(<DestinationsTab perms={ADMIN} destinations={[BASE]} loadUtilization={load} />);
    expect(load).not.toHaveBeenCalled();
    expect(screen.queryByText(/Aprovechamiento de la caché:/)).toBeNull();
  });

  it("muestra el aprovechamiento por destino y «sin datos» donde el destino no informó caché", async () => {
    const util = () => Promise.resolve({
      "d-1": { cache_requests: 4, cache_read_tokens: 600, cache_write_tokens: 100, input_tokens: 1000, cache_hit_rate: 0.6 },
      "d-2": { cache_requests: 0, cache_read_tokens: 0, cache_write_tokens: 0, input_tokens: 0, cache_hit_rate: null },
    });
    render(<DestinationsTab perms={ADMIN} destinations={[BASE, SIN_CACHE]} loadUtilization={util} />);
    fireEvent.click(screen.getByRole("button", { name: /ver aprovechamiento de la caché/i }));
    expect(await within(fila("GLM UE")).findByText(/Aprovechamiento de la caché: 60 %/)).toBeTruthy();
    expect(within(fila("GLM UE")).getByText(/4 pedidos/)).toBeTruthy();
    expect(within(fila("Qwen UE")).getByText(/Aprovechamiento de la caché: sin datos/)).toBeTruthy();
  });

  it("si no se pueden leer los costos avisa y el resto de la pestaña sigue", async () => {
    render(<DestinationsTab perms={ADMIN} destinations={[BASE]} loadUtilization={() => Promise.reject(new Error("403"))} />);
    fireEvent.click(screen.getByRole("button", { name: /ver aprovechamiento de la caché/i }));
    expect(await screen.findByText(/No se pudo leer el aprovechamiento/)).toBeTruthy();
    expect(within(fila("GLM UE")).getByLabelText("Marcas de caché")).toBeTruthy();
  });

  it("al cambiar una casilla guarda las capacidades FUSIONADAS con las que ya tiene y recarga", async () => {
    const reload = vi.fn();
    render(<DestinationsTab perms={ADMIN} destinations={[BASE]} loadUtilization={noUtil} reload={reload} />);
    fireEvent.click(within(fila("GLM UE")).getByLabelText("Afinidad de sesión"));
    await waitFor(() => expect(patchEntry).toHaveBeenCalledTimes(1));
    expect(patchEntry).toHaveBeenCalledWith("d-1", { features: { cache_control: true, session_affinity: true, thinking: true } });
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it("guarda los precios de caché en USD por token (la pantalla los pide por millón)", async () => {
    render(<DestinationsTab perms={ADMIN} destinations={[SIN_CACHE]} loadUtilization={noUtil} />);
    const row = within(fila("Qwen UE"));
    fireEvent.change(row.getByLabelText("Caché: lectura (USD por millón)"), { target: { value: "0,05" } });
    fireEvent.change(row.getByLabelText("Caché: escritura (USD por millón)"), { target: { value: "0,375" } });
    fireEvent.click(row.getByRole("button", { name: /guardar precio de caché/i }));
    await waitFor(() => expect(patchEntry).toHaveBeenCalledTimes(1));
    const [id, body] = patchEntry.mock.calls[0] as [string, Record<string, number>];
    expect(id).toBe("d-2");
    expect(body.price_cache_read).toBeCloseTo(0.05e-6, 12);
    expect(body.price_cache_write).toBeCloseTo(0.375e-6, 12);
  });

  it("rechaza un precio de caché que no es un número", () => {
    render(<DestinationsTab perms={ADMIN} destinations={[SIN_CACHE]} loadUtilization={noUtil} />);
    const row = within(fila("Qwen UE"));
    fireEvent.change(row.getByLabelText("Caché: lectura (USD por millón)"), { target: { value: "abc" } });
    fireEvent.click(row.getByRole("button", { name: /guardar precio de caché/i }));
    expect(patchEntry).not.toHaveBeenCalled();
    expect(row.getByText(/Un número en USD por millón/)).toBeTruthy();
  });

  it("en modo consulta las casillas y los campos están deshabilitados", () => {
    render(<DestinationsTab perms={LECTOR} destinations={[BASE]} loadUtilization={noUtil} />);
    const row = within(fila("GLM UE"));
    expect((row.getByLabelText("Marcas de caché") as HTMLInputElement).disabled).toBe(true);
    expect((row.getByLabelText("Afinidad de sesión") as HTMLInputElement).disabled).toBe(true);
    expect(row.queryByRole("button", { name: /guardar precio de caché/i })).toBeNull();
  });

  it("un destino de la instalación solo lo cambia el super administrador", () => {
    const inst = { ...BASE, level: "installation" } as Destination;
    const { unmount } = render(<DestinationsTab perms={ADMIN} destinations={[inst]} loadUtilization={noUtil} />);
    expect((within(fila("GLM UE")).getByLabelText("Marcas de caché") as HTMLInputElement).disabled).toBe(true);
    unmount();
    render(<DestinationsTab perms={permissionsFor("super_admin")} destinations={[inst]} loadUtilization={noUtil} />);
    expect((within(fila("GLM UE")).getByLabelText("Marcas de caché") as HTMLInputElement).disabled).toBe(false);
  });

  it("muestra el error si el guardado falla y no pierde lo escrito", async () => {
    patchEntry.mockRejectedValueOnce(new Error("No se pudo guardar"));
    render(<DestinationsTab perms={ADMIN} destinations={[BASE]} loadUtilization={noUtil} />);
    fireEvent.click(within(fila("GLM UE")).getByLabelText("Marcas de caché"));
    expect(await screen.findByText(/No se pudo guardar/)).toBeTruthy();
  });
});
