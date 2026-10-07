// Pestaña «Destinos»: VISTA del catálogo único (069 E3). Los destinos de la redirección son los modelos
// del catálogo (activos, de texto, propios u ofrecidos a la organización): se dan de alta, se editan, se
// archivan, se habilitan y se ofrecen en «Modelos». Acá solo se ve cuáles puede usar la organización, qué
// reglas los usan y qué destinos que las reglas nombran ya no están disponibles.
import React from "react";
import { Button, Card, StatusBadge } from "../../../frontend/src/components/ui";
import { catalogApi } from "../catalog/api";
import { us5Api } from "./api";
import { PROVIDER_LABELS } from "./catalog";
import {
  buildCacheFeatures, cacheFlags, cachePriceLabel, capabilityLabel, Destination, destinationStatus, parseCachePrice,
  priceLabel, Rule, RuleWarning, Permissions,
} from "./helpers";
import { EmptyRow, Notice, tableClass, tdClass, thClass } from "./ui";

/** Aprovechamiento de la caché de un destino (de `cost-comparison`, 057 FR-046): lo que el destino informó en sus pedidos. */
export interface CacheUtilization {
  cache_requests: number; cache_read_tokens: number; cache_write_tokens: number;
  input_tokens: number; cache_hit_rate: number | null;
}

const DAY_MS = 86_400_000;

/** Aprovechamiento por destino de los últimos 30 días (todo el tráfico de la organización). */
export async function loadCacheUtilization(): Promise<Record<string, CacheUtilization>> {
  const to = new Date();
  const from = new Date(to.getTime() - 30 * DAY_MS);
  const costs = await us5Api.costs({ from: from.toISOString(), to: to.toISOString(), scope: "tenant" });
  const out: Record<string, CacheUtilization> = {};
  for (const d of costs.by_destination as unknown as (CacheUtilization & { destination_id: string })[]) out[d.destination_id] = d;
  return out;
}

function utilizationText(u: CacheUtilization | undefined): string {
  if (!u || u.cache_hit_rate === null || u.cache_requests === 0) return "Aprovechamiento de la caché: sin datos";
  const pct = Math.round(u.cache_hit_rate * 100);
  return `Aprovechamiento de la caché: ${pct} % (${u.cache_requests} ${u.cache_requests === 1 ? "pedido" : "pedidos"})`;
}

/** Casillas «marcas de caché» y «afinidad de sesión», precio de caché y aprovechamiento de UN destino. Escribe en el
 *  catálogo (Modelos) con el mismo permiso que ese alta: organización ⇒ administración; instalación ⇒ super administrador. */
const CacheSettings: React.FC<{
  d: Destination; canEdit: boolean; loaded: boolean; utilization?: CacheUtilization; reload?: () => void;
}> = ({ d, canEdit, loaded, utilization, reload }) => {
  const flags = cacheFlags(d);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [read, setRead] = React.useState("");
  const [write, setWrite] = React.useState("");
  const [priceError, setPriceError] = React.useState<string | null>(null);
  const priceNote = cachePriceLabel(d);

  const save = async (body: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await catalogApi.patchEntry(d.id, body);
      reload?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };
  const toggle = (key: "cache_control" | "session_affinity") => (e: React.ChangeEvent<HTMLInputElement>) =>
    save({ features: buildCacheFeatures(d.capability_profile, { [key]: e.target.checked }) });
  const savePrice = () => {
    const r = parseCachePrice(read);
    const w = parseCachePrice(write);
    const bad = r.error ?? w.error;
    setPriceError(bad ?? null);
    if (bad) return;
    const body: Record<string, number> = {};
    if (r.perToken !== null) body.price_cache_read = r.perToken;
    if (w.perToken !== null) body.price_cache_write = w.perToken;
    if (Object.keys(body).length) void save(body);
  };

  return (
    <div className="mt-2 pt-2 border-t border-border space-y-1">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <label className="text-xs flex items-center gap-1">
          <input type="checkbox" checked={flags.cache_control} disabled={!canEdit || busy} onChange={toggle("cache_control")} />
          Marcas de caché
        </label>
        <label className="text-xs flex items-center gap-1">
          <input type="checkbox" checked={flags.session_affinity} disabled={!canEdit || busy} onChange={toggle("session_affinity")} />
          Afinidad de sesión
        </label>
      </div>
      {priceNote && <div className="text-xs text-text-tertiary">{priceNote}</div>}
      {canEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs">
            <span className="block text-text-tertiary">Caché: lectura (USD por millón)</span>
            <input aria-label="Caché: lectura (USD por millón)" className="border border-border rounded px-1 py-0.5 w-24 text-xs"
              inputMode="decimal" value={read} onChange={e => setRead(e.target.value)} />
          </label>
          <label className="text-xs">
            <span className="block text-text-tertiary">Caché: escritura (USD por millón)</span>
            <input aria-label="Caché: escritura (USD por millón)" className="border border-border rounded px-1 py-0.5 w-24 text-xs"
              inputMode="decimal" value={write} onChange={e => setWrite(e.target.value)} />
          </label>
          <Button size="sm" variant="secondary" disabled={busy} onClick={savePrice}>Guardar precio de caché</Button>
        </div>
      )}
      {priceError && <div className="text-xs text-red-600">{priceError}</div>}
      {error && <div className="text-xs text-red-600">{error}</div>}
      {loaded && <div className="text-xs text-text-tertiary">{utilizationText(utilization)}</div>}
    </div>
  );
};

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
  /** Recarga la pantalla después de guardar la caché de un destino. */
  reload?: () => void;
  /** Aprovechamiento de la caché por destino (por defecto, `cost-comparison` de los últimos 30 días). */
  loadUtilization?: () => Promise<Record<string, CacheUtilization>>;
}> = ({ perms, destinations, rules = [], onOpenModels, reload, loadUtilization = loadCacheUtilization }) => {
  const usedBy = (id: string) => rules.filter(r => r.targets.includes(id)).length;
  const gone = unavailableTargets(rules);
  // El aprovechamiento se pide a demanda (botón): no suma una llamada a los costos cada vez que se abre la pestaña y los roles
  // sin acceso a los costos no ven un error que no pidieron.
  const [utilization, setUtilization] = React.useState<Record<string, CacheUtilization> | null>(null);
  const [utilLoading, setUtilLoading] = React.useState(false);
  const [utilError, setUtilError] = React.useState<string | null>(null);
  const showUtilization = async () => {
    setUtilLoading(true);
    setUtilError(null);
    try {
      setUtilization(await loadUtilization());
    } catch {
      setUtilError("No se pudo leer el aprovechamiento de la caché (los costos los ve administración y cumplimiento).");
    } finally {
      setUtilLoading(false);
    }
  };
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
      <div className="mb-3 flex items-center gap-3">
        <Button size="sm" variant="secondary" disabled={utilLoading} onClick={showUtilization}>
          Ver aprovechamiento de la caché (30 días)
        </Button>
        {utilError && <span className="text-xs text-red-600">{utilError}</span>}
      </div>
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
                      <CacheSettings d={d} loaded={utilization !== null} utilization={utilization?.[d.id]} reload={reload}
                        canEdit={d.level === "installation" ? perms.isSuper : perms.canAdmin} />
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
