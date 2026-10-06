// Pestaña «Acceso» de «Modelos» (US2): quién puede usar qué modelo. Perfiles de empresa, techos por
// riesgo del AI Act, asignaciones, perfil por llave y accesos efectivos, sobre `/api/v1/access/*`
// (`accessApi.ts`, `access/`). Si esta instalación todavía no tiene ese backend (404 en `/profiles`)
// la pestaña lo dice con claridad y no restringe nada.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card, cn } from "../../../frontend/src/components/ui";
import { authStorage } from "../../../frontend/src/services/auth";
import { catalogApi } from "../catalog/api";
import { Lookups, sessionRole } from "../redirect/helpers";
import { redirectApi } from "../redirect/api";
import { Notice } from "../redirect/ui";
import { accessApi, AccessApiError, Profile } from "./accessApi";
import { AssignmentsPanel } from "./access/AssignmentsPanel";
import { CeilingsPanel } from "./access/CeilingsPanel";
import { EffectivePanel } from "./access/EffectivePanel";
import { accessPermsFor } from "./access/helpers";
import { KeysPanel } from "./access/KeysPanel";
import { ProfilesPanel } from "./access/ProfilesPanel";
import type { AccessCtx } from "./access/types";

const SUBTABS = [
  { id: "profiles", label: "Perfiles" },
  { id: "ceilings", label: "Techos por riesgo AI Act" },
  { id: "assignments", label: "Asignaciones" },
  { id: "keys", label: "Llaves" },
  { id: "effective", label: "Efectivos" },
] as const;
type SubTab = (typeof SUBTABS)[number]["id"];

const NO_LOOKUPS: Lookups = { groups: [], users: [], keys: [] };

export const AccessTab: React.FC = () => {
  const role = useMemo(() => sessionRole(authStorage.getToken(), authStorage.getUser()?.role), []);
  const perms = useMemo(() => accessPermsFor(role), [role]);
  const [sub, setSub] = useState<SubTab>("profiles");
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lookups, setLookups] = useState<Lookups>(NO_LOOKUPS);
  const [entries, setEntries] = useState<AccessCtx["entries"]>([]);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const reload = useCallback(async () => {
    setError(null);
    try {
      setProfiles(await accessApi.profiles(true));
      setUnavailable(false);
    } catch (e) {
      if (e instanceof AccessApiError && e.status === 404) setUnavailable(true);
      else setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
    redirectApi.lookups().then(setLookups).catch(() => setLookups(NO_LOOKUPS));
    catalogApi.entries().then(r => setEntries(r.filter(e => e.status !== "archived"))).catch(() => setEntries([]));
  }, [reload]);

  const onKey = (e: React.KeyboardEvent, i: number) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const at = e.key === "Home" ? 0 : e.key === "End" ? SUBTABS.length - 1 : (i + delta + SUBTABS.length) % SUBTABS.length;
    setSub(SUBTABS[at].id);
    refs.current[SUBTABS[at].id]?.focus();
  };

  if (unavailable) {
    return (
      <Notice tone="info">
        El acceso por perfil todavía no está disponible en esta instalación. Mientras tanto no se restringe ningún modelo
        por perfil.
      </Notice>
    );
  }
  if (error) {
    return (
      <Notice tone="error">
        {error}{" "}
        <button type="button" className="underline" onClick={() => void reload()}>Reintentar</button>
      </Notice>
    );
  }
  if (!profiles) return <p role="status" className="text-sm text-text-tertiary">Cargando acceso…</p>;

  const ctx: AccessCtx = { perms, profiles, lookups, entries, reload };
  return (
    <div className="space-y-4">
      {!perms.canAdmin && !perms.canCeiling && (
        <Notice tone="info">Estás en modo consulta: podés ver perfiles, techos y accesos efectivos, pero no cambiarlos.</Notice>
      )}
      <div className="flex gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="Secciones de Acceso">
        {SUBTABS.map((t, i) => (
          <button
            key={t.id}
            ref={el => { refs.current[t.id] = el; }}
            role="tab"
            id={`access-tab-${t.id}`}
            aria-selected={sub === t.id}
            aria-controls="access-panel"
            tabIndex={sub === t.id ? 0 : -1}
            onClick={() => setSub(t.id)}
            onKeyDown={e => onKey(e, i)}
            className={cn(
              "whitespace-nowrap border-b-2 px-3 py-2 text-xs font-semibold transition-all",
              sub === t.id ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-text-primary",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <Card>
        <div role="tabpanel" id="access-panel" aria-labelledby={`access-tab-${sub}`}>
          {sub === "profiles" && <ProfilesPanel ctx={ctx} />}
          {sub === "ceilings" && <CeilingsPanel ctx={ctx} />}
          {sub === "assignments" && <AssignmentsPanel ctx={ctx} />}
          {sub === "keys" && <KeysPanel ctx={ctx} />}
          {sub === "effective" && <EffectivePanel ctx={ctx} />}
        </div>
      </Card>
    </div>
  );
};

export default AccessTab;
