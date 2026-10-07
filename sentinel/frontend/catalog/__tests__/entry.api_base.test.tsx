// Alta de un modelo de empresa con una dirección rechazada por la API (057 H1: solo https y nunca una dirección
// interna o de metadatos): el panel muestra el motivo que da la API, sin mensaje genérico.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CatalogPage } from "../CatalogPage";

const MOTIVO = "la dirección api_base debe usar https y no apuntar a una dirección interna";

describe("alta con api_base rechazada (422)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("muestra el motivo de la API", async () => {
    const token = `h.${btoa(JSON.stringify({ role: "tenant_admin" })).replace(/=+$/, "")}.s`;
    localStorage.setItem("sentinel_session_token", token);
    localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/v1/catalog/entries" && method === "POST") return new Response(JSON.stringify({ detail: MOTIVO }), { status: 422 });
      if (url.startsWith("/api/v1/catalog/entries")) return new Response(JSON.stringify({ data: [] }), { status: 200 });
      if (url === "/api/v1/catalog/credentials" || url === "/api/v1/catalog/dpas") return new Response(JSON.stringify({ data: [] }), { status: 200 });
      if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator: false }), { status: 200 });
      return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
    }));
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo modelo" }));
    fireEvent.change(screen.getByLabelText("Proveedor"), { target: { value: "openai_compatible" } });
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Interno" } });
    fireEvent.change(screen.getByLabelText("Modelo real"), { target: { value: "m" } });
    fireEvent.change(screen.getByLabelText("Dirección base"), { target: { value: "http://169.254.169.254/latest" } });
    fireEvent.change(screen.getByLabelText("Nombre de la credencial"), { target: { value: "Clave" } });
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: "clave-de-prueba" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear modelo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(MOTIVO.charAt(0).toUpperCase() + MOTIVO.slice(1));
  });
});
