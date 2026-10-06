// Pantalla «Catálogo de modelos» (spec 069, US1): lista única de modelos con semáforo de
// cumplimiento, alta, ficha, ofertas y credenciales sobre `/api/v1/catalog/*`.
// Los botones de escritura se muestran según el rol; el backend aplica los permisos igual.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader, cn } from "../../../frontend/src/components/ui";
import { authStorage } from "../../../frontend/src/services/auth";
import { redirectApi } from "../redirect/api";
import { sessionRole } from "../redirect/helpers";
import { Notice } from "../redirect/ui";
import { catalogApi } from "./api";
import { CredentialsTab } from "./CredentialsTab";
import { CredentialRow, EntryView, permissionsFor } from "./helpers";
import { ModelsTab } from "./ModelsTab";

type Tab = "models" | "credentials";
const TABS: { id: Tab; label: string }[] = [
  { id: "models", label: "Modelos" },
  { id: "credentials", label: "Credenciales" },
];

export const CatalogPage: React.FC = () => {
  const role = useMemo(() => sessionRole(authStorage.getToken(), authStorage.getUser()?.role), []);
  const [operator, setOperator] = useState(false);
  const perms = useMemo(() => permissionsFor(role, operator), [role, operator]);
  useEffect(() => {
    redirectApi.capabilities().then(c => setOperator(Boolean(c?.operator))).catch(() => setOperator(false));
  }, []);
  const [tab, setTab] = useState<Tab>("models");
  const [entries, setEntries] = useState<EntryView[]>([]);
  const [credentials, setCredentials] = useState<CredentialRow[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      // Las credenciales las lista solo administración; para el resto la pestaña explica por qué no hay.
      const [rows, creds] = await Promise.all([
        catalogApi.entries(showArchived),
        perms.canAdmin ? catalogApi.credentials() : Promise.resolve([] as CredentialRow[]),
      ]);
      setEntries(rows);
      setCredentials(creds);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [showArchived, perms.canAdmin]);

  useEffect(() => { void reload(); }, [reload]);

  return (
    <div>
      <PageHeader
        title="Catálogo de modelos"
        subtitle="Todos los modelos que podés usar, con qué credencial se sirven y qué tan admisibles son según su ficha de cumplimiento."
      />
      {!perms.canAdmin && !loading && !error && (
        <Notice tone="info">
          Estás en modo consulta: podés ver el catálogo{perms.canSheetRole ? " y completar las fichas de cumplimiento" : ""}.
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
          {tab === "models" && (
            <ModelsTab perms={perms} entries={entries} credentials={credentials} showArchived={showArchived}
              setShowArchived={setShowArchived} reload={reload} />
          )}
          {tab === "credentials" && (perms.canAdmin
            ? <CredentialsTab perms={perms} credentials={credentials} entries={entries} reload={reload} />
            : <Notice tone="info">Las credenciales las administra el rol de administración. Acá solo ves, en cada modelo, si tiene una credencial guardada.</Notice>)}
        </div>
      )}
    </div>
  );
};

export default CatalogPage;
