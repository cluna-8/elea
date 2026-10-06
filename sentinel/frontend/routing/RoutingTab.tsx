// «Ruteo» dentro de «Modelos»: cómo se elige el modelo de cada pedido. Tres sub-pestañas:
// por contenido (auto-router semántico), por política (redirección de la 068) y por costo (reservada).
import React, { useState } from "react";
import { cn } from "../../../frontend/src/components/ui";
import { ContentRouting } from "./ContentRouting";
import { CostRouting } from "./CostRouting";
import { RedirectionRouting } from "./RedirectionRouting";

type Sub = "content" | "redirect" | "cost";
const SUBS: { id: Sub; label: string }[] = [
  { id: "content", label: "Contenido" },
  { id: "redirect", label: "Redirección" },
  { id: "cost", label: "Costo" },
];

export const RoutingTab: React.FC<{ onOpenModels?: () => void }> = ({ onOpenModels }) => {
  const [sub, setSub] = useState<Sub>("content");
  return (
    <div>
      <div className="mb-4 flex gap-1 overflow-x-auto" role="tablist" aria-label="Tipo de ruteo">
        {SUBS.map(s => (
          <button
            key={s.id}
            type="button"
            role="tab"
            id={`routing-tab-${s.id}`}
            aria-selected={sub === s.id}
            aria-controls="routing-panel"
            onClick={() => setSub(s.id)}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all",
              sub === s.id ? "bg-primary-tint text-primary" : "text-text-secondary hover:text-text-primary",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="routing-panel" aria-labelledby={`routing-tab-${sub}`}>
        {sub === "content" && <ContentRouting />}
        {sub === "redirect" && <RedirectionRouting onOpenModels={onOpenModels} />}
        {sub === "cost" && <CostRouting />}
      </div>
    </div>
  );
};

export default RoutingTab;
