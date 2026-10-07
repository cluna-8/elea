// «Techos por riesgo AI Act»: un perfil de techo por nivel; lo escribe solo cumplimiento.
import React, { useCallback, useEffect, useState } from "react";
import { Button } from "../../../../frontend/src/components/ui";
import { Notice, SelectField } from "../../redirect/ui";
import { accessApi, Ceilings, RiskLevel } from "../accessApi";
import { RISK_LEVELS } from "./helpers";
import type { AccessCtx } from "./types";

export const CeilingsPanel: React.FC<{ ctx: AccessCtx }> = ({ ctx }) => {
  const [saved, setSaved] = useState<Ceilings | null>(null);
  const [draft, setDraft] = useState<Ceilings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const options = ctx.profiles.filter(p => p.kind === "ceiling" && !p.archived).map(p => ({ value: p.id, label: p.name }));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const c = await accessApi.ceilings();
      setSaved(c);
      setDraft(c);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const changed = (Object.keys(draft ?? {}) as RiskLevel[]).filter(k => (draft?.[k] ?? null) !== (saved?.[k] ?? null));
  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const body: Partial<Ceilings> = {};
      for (const k of changed) body[k] = draft[k] ?? null;
      const next = await accessApi.putCeilings(body);
      setSaved(next);
      setDraft(next);
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
        Cada nivel de riesgo del AI Act tiene un techo: ningún perfil, de ningún sujeto, puede dar acceso a modelos por encima de él.
        Un uso sin clasificar se rige por el techo más estricto.
      </p>
      {!ctx.perms.canCeiling && (
        <Notice tone="info">Solo el rol de cumplimiento puede cambiar los techos. Acá los ves de solo lectura.</Notice>
      )}
      {error && <Notice tone="error">{error}{" "}<button type="button" className="underline" onClick={() => void load()}>Reintentar</button></Notice>}
      {done && <Notice tone="ok">Techos guardados.</Notice>}
      {loading ? (
        <p role="status" className="text-sm text-text-tertiary">Cargando techos…</p>
      ) : draft && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {RISK_LEVELS.map(l => (
              <SelectField key={l.id} label={l.label} hint={l.hint} value={draft[l.id] ?? ""}
                disabled={!ctx.perms.canCeiling || busy} placeholder="Sin techo asignado" options={options}
                onChange={v => { setDone(false); setDraft({ ...draft, [l.id]: v || null }); }} />
            ))}
          </div>
          {ctx.perms.canCeiling && (
            <Button onClick={() => void save()} disabled={busy || changed.length === 0}>
              {busy ? "Guardando…" : "Guardar techos"}
            </Button>
          )}
        </>
      )}
    </div>
  );
};
