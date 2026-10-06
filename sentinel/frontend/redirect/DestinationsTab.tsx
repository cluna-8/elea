// Pestaña «Destinos»: VISTA del catálogo único (069 E3). Los destinos de la redirección son los modelos
// del catálogo (activos, de texto, propios u ofrecidos a la organización): se dan de alta, se editan, se
// archivan, se habilitan y se ofrecen en «Modelos». Acá solo se ve cuáles puede usar la organización, qué
// reglas los usan y qué destinos que las reglas nombran ya no están disponibles.
import React from "react";
import { Button, Card, StatusBadge } from "../../../frontend/src/components/ui";
import { PROVIDER_LABELS } from "./catalog";
import {
  capabilityLabel, Destination, destinationStatus, priceLabel, Rule, RuleWarning, Permissions,
} from "./helpers";
import { EmptyRow, Notice, tableClass, tdClass, thClass } from "./ui";

const WARNING_TEXT: Record<string, string> = {
  destination_unavailable: "Ya no está disponible: se archivó, se desactivó, cambió de tipo o no existe en Modelos.",
  offer_withdrawn: "Era un modelo de la instalación y ya no se ofrece a tu organización.",
};

/** Destinos que las reglas nombran y hoy no se pueden usar (avisos derivados por el backend), con cuántas reglas los usan. */
export function unavailableTargets(rules: Rule[]): { id: string; code: string; rules: number }[] {
  const found = new Map<string, { id: string; code: string; rules: number }>();
  for (const r of rules) {
    for (const w of (r.warnings ?? []) as RuleWarning[]) {
      const cur = found.get(w.destination_id);
      if (cur) cur.rules += 1;
      else found.set(w.destination_id, { id: w.destination_id, code: w.code, rules: 1 });
    }
  }
  return Array.from(found.values());
}

export const DestinationsTab: React.FC<{
  perms: Permissions;
  destinations: Destination[];
  rules?: Rule[];
  /** Lleva a la sección «Modelos» de la pantalla (donde se dan de alta y se editan los destinos). */
  onOpenModels?: () => void;
}> = ({ perms, destinations, rules = [], onOpenModels }) => {
  const usedBy = (id: string) => rules.filter(r => r.targets.includes(id)).length;
  const gone = unavailableTargets(rules);
  return (
    <div>
      <Notice tone="info">
        Los destinos son los modelos del catálogo: se dan de alta, se editan, se archivan, se habilitan y se ofrecen
        en <strong>Modelos</strong>{perms.canAdmin ? "" : " (lo hace el rol de administración)"}. Acá ves los que tu
        organización puede usar en las reglas y en cuáles están.{" "}
        {onOpenModels && (
          <Button size="sm" variant="secondary" onClick={onOpenModels}>Ir a Modelos</Button>
        )}
      </Notice>
      {gone.length > 0 && (
        <Notice tone="error">
          <p className="font-semibold">Hay reglas que nombran destinos que ya no están disponibles</p>
          <ul className="list-disc list-inside mt-1">
            {gone.map(g => (
              <li key={g.id}>
                <span className="font-mono text-xs">{g.id}</span> — {WARNING_TEXT[g.code] ?? "No está disponible."}{" "}
                ({g.rules} {g.rules === 1 ? "regla" : "reglas"}). Reponelo en Modelos o cambialo en la regla.
              </li>
            ))}
          </ul>
        </Notice>
      )}
      <Card noPadding title="Destinos disponibles">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Nombre</th><th className={thClass}>Proveedor · modelo</th>
              <th className={thClass}>Jurisdicción</th><th className={thClass}>Nivel</th>
              <th className={thClass}>Estado</th><th className={thClass}>Reglas que lo usan</th>
            </tr></thead>
            <tbody>
              {destinations.length === 0 && (
                <EmptyRow cols={6}>
                  Todavía no hay modelos disponibles para la redirección: cargalos en Modelos.
                </EmptyRow>
              )}
              {destinations.map(d => {
                const st = destinationStatus(d);
                const n = usedBy(d.id);
                return (
                  <tr key={d.id}>
                    <td className={tdClass}>
                      <div className="font-medium text-text-primary">{d.name}</div>
                      {d.public_id && <div className="text-xs text-text-tertiary font-mono">{d.public_id}</div>}
                      <div className="text-xs text-text-tertiary">{d.has_credential ? "Credencial guardada" : "Sin credencial"}</div>
                    </td>
                    <td className={tdClass}>
                      <div>{PROVIDER_LABELS[d.provider] ?? d.provider}</div>
                      <div className="text-xs text-text-tertiary font-mono">{d.real_model}</div>
                      <div className="text-xs text-text-tertiary">
                        Ventana: {d.context_window ? d.context_window.toLocaleString("es") : "sin declarar"}
                      </div>
                      <div className="text-xs text-text-tertiary">{priceLabel(d)}</div>
                      <div className="text-xs text-text-tertiary">{capabilityLabel(d)}</div>
                      {!!d.unsupported_params?.length && (
                        <div className="text-xs text-text-tertiary">No acepta: {d.unsupported_params.join(", ")}</div>
                      )}
                    </td>
                    <td className={tdClass}>
                      <div>Inferencia: {d.inference_jurisdiction ?? "—"}</div>
                      <div className="text-xs text-text-tertiary">Entidad: {d.entity_jurisdiction ?? "—"}</div>
                    </td>
                    <td className={tdClass}>{d.level === "installation" ? "Instalación" : "Organización"}</td>
                    <td className={tdClass}><StatusBadge tone={st.tone} dot>{st.label}</StatusBadge></td>
                    <td className={tdClass}>{n === 0 ? "Ninguna" : n === 1 ? "1 regla" : `${n} reglas`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
