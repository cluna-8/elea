// Pantalla única «Modelos» (spec 069, US7): reemplaza a la pantalla de modelos de la base y a
// «Catálogo de modelos». Pestañas Modelos y Credenciales (catálogo), Acceso, Consumo y Routing.
// Los botones de escritura se muestran según el rol; el backend aplica los permisos igual.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageHeader, cn } from "../../../frontend/src/components/ui";
import { authStorage } from "../../../frontend/src/services/auth";
import { catalogApi } from "../catalog/api";
import { CredentialsTab } from "../catalog/CredentialsTab";
import { CredentialRow, permissionsFor } from "../catalog/helpers";
import { redirectApi } from "../redirect/api";
import { sessionRole } from "../redirect/helpers";
import { Notice } from "../redirect/ui";
import { RoutingTab } from "../routing/RoutingTab";
import { AccessTab } from "./AccessTab";
import { ModelEntry, ModelsList } from "./ModelsList";
import { UsageTab } from "./UsageTab";

type Tab = "models" | "credentials" | "access" | "usage" | "routing";
const TABS: { id: Tab; label: string }[] = [
  { id: "models", label: "Modelos" },
  { id: "credentials", label: "Credenciales" },
  { id: "access", label: "Acceso" },
  { id: "usage", label: "Consumo" },
  { id: "routing", label: "Routing" },
];

export const ModelsScreen: React.FC = () => {
  const role = useMemo(() => sessionRole(authStorage.getToken(), authStorage.getUser()?.role), []);
  const [operator, setOperator] = useState(false);
  const perms = useMemo(() => permissionsFor(role, operator), [role, operator]);
  useEffect(() => {
    redirectApi.capabilities().then(c => setOperator(Boolean(c?.operator))).catch(() => setOperator(false));
  }, []);
  const [tab, setTab] = useState<Tab>("models");
  const [entries, setEntries] = useState<ModelEntry[]>([]);
  const [credentials, setCredentials] = useState<CredentialRow[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const reload = useCallback(async () => {
    setError(null);
    try {
      // Las credenciales las lista solo administración; para el resto la pestaña explica por qué no hay.
      const [rows, creds] = await Promise.all([
        catalogApi.entries(showArchived),
        perms.canAdmin ? catalogApi.credentials() : Promise.resolve([] as CredentialRow[]),
      ]);
      setEntries(rows as ModelEntry[]);
      setCredentials(creds);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [showArchived, perms.canAdmin]);

  useEffect(() => { void reload(); }, [reload]);

  const onTabKey = (e: React.KeyboardEvent, i: number) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const at = e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : (i + delta + TABS.length) % TABS.length;
    setTab(TABS[at].id);
    tabRefs.current[TABS[at].id]?.focus();
  };

  const catalogTab = tab === "models" || tab === "credentials";

  return (
    <div>
      <PageHeader
        title="Modelos"
        subtitle="Todos los modelos que podés usar, con qué credencial se sirven, quién accede a cada uno y cuánto consumen."
      />
      {!perms.canAdmin && !loading && !error && tab === "models" && (
        <Notice tone="info">
          Estás en modo consulta: podés ver los modelos{perms.canSheetRole ? " y completar las fichas de cumplimiento" : ""}.
        </Notice>
      )}
      {error && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="Secciones de Modelos">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={el => { tabRefs.current[t.id] = el; }}
            role="tab"
            id={`models-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="models-panel"
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            onKeyDown={e => onTabKey(e, i)}
            className={cn(
              "whitespace-nowrap border-b-2 px-4 py-2 text-xs font-semibold transition-all",
              tab === t.id ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-text-primary",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="models-panel" aria-labelledby={`models-tab-${tab}`}>
        {catalogTab && loading ? (
          <p className="text-sm text-text-tertiary">Cargando…</p>
        ) : (
          <>
            {tab === "models" && (
              <ModelsList perms={perms} entries={entries} credentials={credentials} showArchived={showArchived}
                setShowArchived={setShowArchived} reload={reload} />
            )}
            {tab === "credentials" && (perms.canAdmin
              ? <CredentialsTab perms={perms} credentials={credentials} entries={entries} reload={reload} />
              : <Notice tone="info">Las credenciales las administra el rol de administración. Acá solo ves, en cada modelo, si tiene una credencial guardada.</Notice>)}
            {tab === "access" && <AccessTab />}
            {tab === "usage" && <UsageTab />}
            {tab === "routing" && <RoutingTab onOpenModels={() => setTab("models")} />}
          </>
        )}
      </div>
    </div>
  );
};

export default ModelsScreen;
