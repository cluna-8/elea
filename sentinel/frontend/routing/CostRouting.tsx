// Ruteo por costo v1 (069 US10): cada regla de redirección puede elegir, entre sus destinos elegibles,
// el más barato primero (precio de entrada + salida por millón de tokens). Sin precio queda al final.
// Misma API y mismo criterio de permisos que la pestaña «Reglas» de la redirección.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Card, StatusBadge } from "../../../frontend/src/components/ui";
import { authStorage } from "../../../frontend/src/services/auth";
import { redirectApi } from "../redirect/api";
import { FACE_LABELS } from "../redirect/catalog";
import { Destination, permissionsFor, PublishedModel, publishedLabel, Rule, sessionRole } from "../redirect/helpers";
import { EmptyRow, Notice, tableClass, tdClass, thClass } from "../redirect/ui";

const fmt = (n: number) => n.toLocaleString("es-AR", { maximumFractionDigits: 4 });

/** Costo estimado por millón de tokens (entrada + salida) o `null` si el destino no tiene precio. */
export function estimatedCost(d: Destination | undefined): number | null {
  const p = d?.price_override;
  return p && Number.isFinite(p.input_per_mtok) && Number.isFinite(p.output_per_mtok)
    ? p.input_per_mtok + p.output_per_mtok : null;
}

export const CostRouting: React.FC = () => {
  const role = useMemo(() => sessionRole(authStorage.getToken(), authStorage.getUser()?.role), []);
  const [operator, setOperator] = useState(false);
  const perms = useMemo(() => permissionsFor(role, operator), [role, operator]);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [published, setPublished] = useState<PublishedModel[]>([]);
  const [destinations, setDestinations] = useState<Destination[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, p, d] = await Promise.all([redirectApi.rules(), redirectApi.published(), redirectApi.destinations()]);
      setRules(r); setPublished(p); setDestinations(d);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    redirectApi.capabilities().then(c => setOperator(Boolean(c?.operator))).catch(() => setOperator(false));
    void load();
  }, [load]);

  const toggle = async (rule: Rule) => {
    setBusy(rule.id);
    try {
      await redirectApi.patchRule(rule.id, { strategy: rule.strategy === "cheapest" ? "order" : "cheapest" });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const ruleLabel = (r: Rule) => {
    const p = published.find(x => x.id === r.published_model_id);
    return p ? `${FACE_LABELS[p.face]} · ${publishedLabel(p)}` : r.family_tier ? `Tier ${r.family_tier}` : "(id borrado)";
  };

  return (
    <Card title="Ruteo por costo" actions={<StatusBadge tone="neutral">Primera versión</StatusBadge>}>
      <div className="space-y-4 text-sm text-text-secondary">
        <p>
          Cada regla puede elegir entre sus destinos el más barato primero. Es la primera versión del routing por
          costo; se afina con el equipo. El costo se compara con el precio por millón de tokens (entrada más salida)
          de cada destino; si empatan, vale el orden de la regla, y los que no tienen precio quedan al final.
          Solo cuentan los destinos que hoy pueden servir el pedido.
        </p>
        {error && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={thClass}>Regla</th>
                <th className={thClass}>Destinos (orden de la regla)</th>
                <th className={thClass}>Más barato primero</th>
              </tr>
            </thead>
            <tbody>
              {rules !== null && rules.length === 0 && (
                <EmptyRow cols={3}>Todavía no hay reglas de redirección. Se crean en la pestaña Redirección.</EmptyRow>
              )}
              {(rules ?? []).map(r => {
                const on = r.strategy === "cheapest";
                return (
                  <tr key={r.id}>
                    <td className={tdClass}><span className="font-medium text-text-primary">{ruleLabel(r)}</span></td>
                    <td className={tdClass}>
                      <ul className="space-y-1">
                        {r.targets.map(id => {
                          const d = destinations.find(x => x.id === id);
                          const cost = estimatedCost(d);
                          return (
                            <li key={id}>
                              <span>{d?.name ?? "(destino no disponible)"}</span>{" "}
                              {cost !== null
                                ? <span className="text-xs">{fmt(cost)} USD/M</span>
                                : <span className="text-xs text-warn">sin precio: queda al final</span>}
                            </li>
                          );
                        })}
                      </ul>
                    </td>
                    <td className={tdClass}>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={on}
                        aria-label={`Más barato primero: ${ruleLabel(r)}`}
                        disabled={!perms.canAdmin || busy === r.id}
                        onClick={() => void toggle(r)}
                        className="rounded-md border border-border px-3 py-1 text-xs font-semibold disabled:opacity-60"
                      >
                        {on ? "Activado" : "Desactivado"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!perms.canAdmin && <p className="text-xs">Tu rol puede ver las estrategias pero no cambiarlas.</p>}
      </div>
    </Card>
  );
};

export default CostRouting;
