// Semáforo contra la región del perfil (057 T059/T063; FR-030a; research R16, R26): el valor interno sigue siendo
// `eu_ok` pero la etiqueta es «Dentro de <región>», nunca «Admisible» ni «Cumple»; ningún texto fija la UE.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { motivoLabel, newEntryForm, semaforoLabel } from "../helpers";
import { SemaforoBadge } from "../ui";
import { EntryFormFields } from "../EntryForm";
import { RegionBadge } from "../../models/ModelsList";

describe("etiqueta del semáforo por región", () => {
  it("«Dentro de <región>» con region_label; sin él, «Dentro de la región»", () => {
    expect(semaforoLabel({ estado: "eu_ok", motivos: [], region_label: "AMERICAS" } as never)).toBe("Dentro de AMERICAS");
    expect(semaforoLabel({ estado: "eu_ok", motivos: [] })).toBe("Dentro de la región");
    expect(semaforoLabel({ estado: "standard", motivos: [], region_label: "AMERICAS" } as never)).toBe("Estándar");
  });

  it("la insignia usa region_label del semáforo o el de la entrada; nunca «Admisible» ni «UE»", () => {
    const { rerender } = render(<SemaforoBadge semaforo={{ estado: "eu_ok", motivos: [], region_label: "AMERICAS" } as never} />);
    expect(screen.getByLabelText("Semáforo: Dentro de AMERICAS")).toBeInTheDocument();
    rerender(<SemaforoBadge semaforo={{ estado: "eu_ok", motivos: [] }} regionLabel="LATAM" />);
    expect(screen.getByText("Dentro de LATAM")).toBeInTheDocument();
    rerender(<SemaforoBadge semaforo={{ estado: "eu_ok", motivos: [] }} />);
    expect(document.body.textContent).not.toMatch(/Admisible|Cumple\b|\bUE\b/);
  });

  it("los motivos no fijan la UE", () => {
    for (const k of ["inferencia_fuera_ue", "registros_fuera_ue", "dpa_region_no_ue"]) {
      expect(motivoLabel(k)).not.toMatch(/\bUE\b|Unión Europea/);
      expect(motivoLabel(k)).toMatch(/región/);
    }
  });

  it("la marca de región de la lista usa in_region y el nombre de la región, no «UE»", () => {
    const { rerender } = render(<RegionBadge value={undefined} inRegion={true} regionLabel="AMERICAS" />);
    expect(screen.getByText("Dentro de AMERICAS")).toBeInTheDocument();
    rerender(<RegionBadge value={undefined} inRegion={false} regionLabel="AMERICAS" />);
    expect(screen.getByText("Fuera de AMERICAS")).toBeInTheDocument();
  });
});

describe("EntryForm", () => {
  it("el texto de ayuda no nombra otro producto (H7)", () => {
    render(<EntryFormFields form={newEntryForm()} setForm={() => undefined} errors={{}} credentials={[]}
      perms={{ isSuper: false, canAdmin: true, canEnable: false, canAddPosture: true, canManagePosture: false, operator: false } as never} />);
    expect(document.body.textContent).toContain("La pasarela los quita antes de llegar al proveedor");
    expect(document.body.textContent).not.toMatch(/Sentinel/);
  });
});
