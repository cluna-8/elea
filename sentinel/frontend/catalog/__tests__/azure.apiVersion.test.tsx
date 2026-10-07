// Aviso (no bloqueo) de la versión de API de Azure en el alta/edición de una credencial (057): por debajo de
// 2025-04-01-preview las herramientas y el razonamiento (Claude Desktop/Code) no se sirven bien por Responses.
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { SecretFields } from "../ui";
import { AZURE_RESPONSES_MIN_API_VERSION, apiVersionBelowResponsesFloor, buildSecretValue, valueFields } from "../helpers";

describe("apiVersionBelowResponsesFloor", () => {
  it.each(["2024-10-21", "2024-12-01-preview", "2025-03-01-preview", " 2023-05-15 "])("%s está por debajo del piso", v => {
    expect(apiVersionBelowResponsesFloor(v)).toBe(true);
  });
  it.each([AZURE_RESPONSES_MIN_API_VERSION, "2025-06-01-preview", "2025-04-01", "2026-01-01-preview"])("%s no avisa", v => {
    expect(apiVersionBelowResponsesFloor(v)).toBe(false);
  });
  it.each(["", "v1", "latest", "2025", "2025-04", undefined])("%s (no es una fecha completa) no avisa", v => {
    expect(apiVersionBelowResponsesFloor(v as string | undefined)).toBe(false);
  });
});

const Harness: React.FC<{ provider: "azure" | "openai"; initial?: Record<string, string> }> = ({ provider, initial = {} }) => {
  const [values, setValues] = useState<Record<string, string>>(initial);
  return <SecretFields fields={valueFields(provider)} values={values} errors={{}} onChange={setValues} />;
};

const WARNING = /herramientas.*razonamiento.*Claude Desktop/is;

describe("aviso de versión de API en el formulario de credencial", () => {
  it("una versión anterior al piso avisa y explica por qué, sin bloquear", () => {
    render(<Harness provider="azure" initial={{ api_key: "k", api_version: "2024-10-21" }} />);
    const aviso = screen.getByRole("status");
    expect(aviso).toHaveTextContent(WARNING);
    expect(aviso).toHaveTextContent(AZURE_RESPONSES_MIN_API_VERSION);
    const built = buildSecretValue(valueFields("azure"), { api_key: "k", api_version: "2024-10-21" });
    expect(built.errors).toEqual({});                                    // aviso, no bloqueo: la credencial se guarda igual
    expect(built.value).toEqual({ api_key: "k", api_version: "2024-10-21" });
  });

  it("aparece y desaparece al editar la versión", () => {
    render(<Harness provider="azure" />);
    expect(screen.queryByRole("status")).toBeNull();
    const input = screen.getByLabelText("Versión de API");
    fireEvent.change(input, { target: { value: "2024-06-01" } });
    expect(screen.getByRole("status")).toHaveTextContent(WARNING);
    fireEvent.change(input, { target: { value: "2025-04-01-preview" } });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("otro proveedor no tiene el campo ni el aviso", () => {
    render(<Harness provider="openai" initial={{ api_key: "k" }} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
