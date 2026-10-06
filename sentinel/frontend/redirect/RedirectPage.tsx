// Pantalla «Redirección de modelos» (spec 068): administra destinos, ids publicados, reglas,
// estado de política, residencia y vista previa, y ofrece kits de cliente, prueba de fidelidad y
// comparador de costos (US5), sobre `/api/v1/redirect/*`.
// Los botones de escritura se muestran según el rol; el backend aplica los permisos igual.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader, cn } from "../../../frontend/src/components/ui";
import { authStorage } from "../../../frontend/src/services/auth";
import { MaskingRelaxation, redirectApi, RegionEffective } from "./api";
import { Destination, Lookups, permissionsFor, PolicyRow, PostureRow, PublishedModel, Rule, sessionRole } from "./helpers";
import { DestinationsTab } from "./DestinationsTab";
import { PublishedTab } from "./PublishedTab";
import { RulesTab } from "./RulesTab";
import { PolicyTab } from "./PolicyTab";
import { EffectivePosture, ResidencyTab } from "./ResidencyTab";
import { PreviewTab } from "./PreviewTab";
import { KitsTab } from "./KitsTab";
import { FidelityTab } from "./FidelityTab";
import { CostsTab } from "./CostsTab";
import { Notice } from "./ui";

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
  region: RegionEffective | null;
  relaxations: MaskingRelaxation[];
  lookups: Lookups;
}

const EMPTY: State = {
  destinations: [], published: [], rules: [], policy: [], postures: [], effective: null, region: null, relaxations: [],
  lookups: { groups: [], users: [], keys: [] },
};

export const RedirectPage: React.FC<{ onOpenModels?: () => void }> = ({ onOpenModels }) => {
  const role = useMemo(() => sessionRole(authStorage.getToken(), authStorage.getUser()?.role), []);
  const [operator, setOperator] = useState(false);
  const [managesRegions, setManagesRegions] = useState<boolean | null>(null);
  const perms = useMemo(() => permissionsFor(role, operator, managesRegions), [role, operator, managesRegions]);
  useEffect(() => {
    redirectApi.capabilities().then(c => {
      setOperator(Boolean(c?.operator));
      setManagesRegions(typeof c?.manages_regions === "boolean" ? c.manages_regions : null);
    }).catch(() => setOperator(false));
  }, []);
  const [tab, setTab] = useState<Tab>("destinations");
  const [data, setData] = useState<State>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      // región y relajaciones (057): un servidor sin esas rutas (404) deja la pestaña como antes
      const [destinations, published, rules, policy, postures, lookups, region, relaxations] = await Promise.all([
        redirectApi.destinations(), redirectApi.published(), redirectApi.rules(), redirectApi.policy(),
        redirectApi.postures(), redirectApi.lookups(),
        redirectApi.regionEffective().catch(() => null), redirectApi.maskingRelaxations().catch(() => []),
      ]);
      setData({
        destinations, published, rules, policy, postures: postures.data,
        effective: postures.effective_tenant_redirected ?? null, region, relaxations, lookups,
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
      <PageHeader
        title="Redirección de modelos"
        subtitle="Qué modelo ve cada herramienta, con qué destino real se sirve y dónde pueden viajar los datos."
      />
      {!perms.canAdmin && !loading && !error && (
        <Notice tone="info">
          Estás en modo consulta: podés ver la configuración{perms.canAddPosture ? " y administrar la residencia" : ""}.
        </Notice>
      )}
      {error && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      <div className="flex gap-1 border-b border-border mb-6 overflow-x-auto" role="tablist">
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
            <ResidencyTab perms={perms} postures={data.postures} effective={data.effective} lookups={data.lookups} reload={reload}
              region={data.region} relaxations={data.relaxations} destinations={data.destinations} />
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

export default RedirectPage;
