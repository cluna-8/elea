// «Llaves»: el perfil de una conexión (solo achica lo que ve la persona, nunca amplía).
import React, { useEffect, useState } from "react";
import { Button } from "../../../../frontend/src/components/ui";
import { Notice, SelectField } from "../../redirect/ui";
import { accessApi } from "../accessApi";
import type { AccessCtx } from "./types";

export const KeysPanel: React.FC<{ ctx: AccessCtx }> = ({ ctx }) => {
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState("");
  const [profile, setProfile] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const options = ctx.profiles.filter(p => p.kind === "key" && !p.archived).map(p => ({ value: p.id, label: p.name }));

  useEffect(() => {
    setWarnings([]);
    setDone(false);
    setError(null);
    if (!key) return;
    let live = true;
    setLoading(true);
    accessApi.keyProfile(key)
      .then(k => { if (live) { setSaved(k.profile_id ?? ""); setProfile(k.profile_id ?? ""); setWarnings(k.warnings ?? []); } })
      .catch(e => { if (live) setError((e as Error).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [key]);

  const save = async () => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const k = await accessApi.putKeyProfile(key, profile || null);
      setSaved(k.profile_id ?? "");
      setProfile(k.profile_id ?? "");
      setWarnings(k.warnings ?? []);
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-text-secondary">
        El perfil de una llave solo puede achicar lo que ve quien la usa: nunca amplía lo que su perfil de empresa o el techo de riesgo permiten.
      </p>
      <SelectField label="Conexión" value={key} onChange={setKey}
        options={ctx.lookups.keys.map(k => ({ value: k.id, label: k.name }))}
        placeholder={ctx.lookups.keys.length ? "Elegí…" : "No hay conexiones para elegir"} />
      {error && <Notice tone="error">{error}</Notice>}
      {key && (loading ? (
        <p role="status" className="text-sm text-text-tertiary">Cargando perfil de la llave…</p>
      ) : (
        <>
          <SelectField label="Perfil de la llave" value={profile} onChange={v => { setProfile(v); setDone(false); }}
            disabled={!ctx.perms.canAdmin || busy} options={options} placeholder="Sin perfil de llave" />
          {done && <Notice tone="ok">Perfil de la llave guardado.</Notice>}
          {warnings.length > 0 && (
            <div role="status" className="rounded-md bg-warn-bg px-4 py-3 text-sm text-warn">
              <p className="mb-1 font-semibold">Advertencias</p>
              <ul className="list-disc pl-5">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          {ctx.perms.canAdmin && (
            <Button onClick={() => void save()} disabled={busy || profile === saved}>
              {busy ? "Guardando…" : "Guardar perfil de la llave"}
            </Button>
          )}
        </>
      ))}
    </div>
  );
};
