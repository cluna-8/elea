// Redirección por política (spec 068) dentro de «Ruteo»: el cuerpo de la pantalla «Redirección de
// modelos» sin su encabezado de página, con las mismas pestañas y la misma API (`/api/v1/redirect/*`).
// Los botones de escritura se muestran según el rol; el backend aplica los permisos igual.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "../../../frontend/src/components/ui";
import { authStorage } from "../../../frontend/src/services/auth";
import { redirectApi } from "../redirect/api";
import { Destination, Lookups, permissionsFor, PolicyRow, PostureRow, PublishedModel, Rule, sessionRole } from "../redirect/helpers";
import { DestinationsTab } from "../redirect/DestinationsTab";
import { PublishedTab } from "../redirect/PublishedTab";
import { RulesTab } from "../redirect/RulesTab";
import { PolicyTab } from "../redirect/PolicyTab";
import { EffectivePosture, ResidencyTab } from "../redirect/ResidencyTab";
import { PreviewTab } from "../redirect/PreviewTab";
import { KitsTab } from "../redirect/KitsTab";
import { FidelityTab } from "../redirect/FidelityTab";
import { CostsTab } from "../redirect/CostsTab";
import { Notice } from "../redirect/ui";

type Tab = "destinations" | "published" | "rules" | "policy" | "residency" | "preview" | "kits" | "fidelity" | "costs";
const TABS: { id: Tab; label: string }[] = [
  { id: "destinations", label: "Destinos" },
  { id: "published", label: "Modelos publicados" },
  { id: "rules", label: "Reglas" },
  { id: "policy", label: "Política" },
  { id: "residency", label: "Residencia" },
  { id: "preview", label: "Vista previa" },
  { id: "kits", label: "Kits" },
  { id: "fidelity", label: "Fidelidad" },
  { id: "costs", label: "Costos" },
];

interface State {
  destinations: Destination[];
  published: PublishedModel[];
  rules: Rule[];
  policy: PolicyRow[];
  postures: PostureRow[];
  effective: EffectivePosture | null;
  lookups: Lookups;
}

const EMPTY: State = {
  destinations: [], published: [], rules: [], policy: [], postures: [], effective: null,
  lookups: { groups: [], users: [], keys: [] },
};

export const RedirectionRouting: React.FC<{ onOpenModels?: () => void }> = ({ onOpenModels }) => {
  const role = useMemo(() => sessionRole(authStorage.getToken(), authStorage.getUser()?.role), []);
  const [operator, setOperator] = useState(false);
  const perms = useMemo(() => permissionsFor(role, operator), [role, operator]);
  useEffect(() => {
    redirectApi.capabilities().then(c => setOperator(Boolean(c?.operator))).catch(() => setOperator(false));
  }, []);
  const [tab, setTab] = useState<Tab>("destinations");
  const [data, setData] = useState<State>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const [destinations, published, rules, policy, postures, lookups] = await Promise.all([
        redirectApi.destinations(), redirectApi.published(), redirectApi.rules(), redirectApi.policy(),
        redirectApi.postures(), redirectApi.lookups(),
      ]);
      setData({
        destinations, published, rules, policy, postures: postures.data,
        effective: postures.effective_tenant_redirected ?? null, lookups,
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  return (
    <div>
      {!perms.canAdmin && !loading && !error && (
        <Notice tone="info">
          Estás en modo consulta: podés ver la configuración{perms.canAddPosture ? " y administrar la residencia" : ""}.
        </Notice>
      )}
      {error && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      <div className="flex gap-1 border-b border-border mb-6 overflow-x-auto" role="tablist" aria-label="Redirección por política">
        {TABS.map(t => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-4 py-2 text-xs font-semibold whitespace-nowrap border-b-2 transition-all",
              tab === t.id ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-text-primary",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="text-sm text-text-tertiary">Cargando…</p>
      ) : (
        <div role="tabpanel">
          {tab === "destinations" && <DestinationsTab perms={perms} destinations={data.destinations} rules={data.rules} onOpenModels={onOpenModels} />}
          {tab === "published" && <PublishedTab perms={perms} published={data.published} lookups={data.lookups} reload={reload} />}
          {tab === "rules" && (
            <RulesTab perms={perms} rules={data.rules} published={data.published} destinations={data.destinations}
              lookups={data.lookups} reload={reload} />
          )}
          {tab === "policy" && <PolicyTab perms={perms} policy={data.policy} lookups={data.lookups} reload={reload} />}
          {tab === "residency" && (
            <ResidencyTab perms={perms} postures={data.postures} effective={data.effective} lookups={data.lookups} reload={reload} />
          )}
          {tab === "preview" && <PreviewTab published={data.published} destinations={data.destinations} lookups={data.lookups} />}
          {tab === "kits" && <KitsTab perms={perms} lookups={data.lookups} />}
          {tab === "fidelity" && <FidelityTab perms={perms} destinations={data.destinations} />}
          {tab === "costs" && <CostsTab lookups={data.lookups} />}
        </div>
      )}
    </div>
  );
};

export default RedirectionRouting;
