// «Asignaciones»: qué perfiles de empresa (0..n) tiene una organización, un grupo o una persona.
import React, { useEffect, useState } from "react";
import { Button } from "../../../../frontend/src/components/ui";
import { CheckField } from "../../catalog/ui";
import { Notice, ReasonDialog, SelectField } from "../../redirect/ui";
import { accessApi, AccessApiError, SubjectType } from "../accessApi";
import type { AccessCtx } from "./types";

const TYPES: { value: SubjectType; label: string }[] = [
  { value: "tenant", label: "Organización" },
  { value: "group", label: "Grupo" },
  { value: "user", label: "Usuario" },
];
/** La organización de la sesión; el backend no necesita su id. */
const TENANT_SUBJECT = "*";

export const AssignmentsPanel: React.FC<{ ctx: AccessCtx }> = ({ ctx }) => {
  const [type, setType] = useState<SubjectType>("tenant");
  const [subject, setSubject] = useState(TENANT_SUBJECT);
  const [saved, setSaved] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [confirmEmpty, setConfirmEmpty] = useState(false);
  const company = ctx.profiles.filter(p => p.kind === "company" && !p.archived);
  const options = type === "group" ? ctx.lookups.groups.map(g => ({ value: g.id, label: g.name }))
    : type === "user" ? ctx.lookups.users.map(u => ({ value: u.id, label: u.username })) : [];

  useEffect(() => {
    if (!subject) { setSaved([]); setSelected([]); return; }
    let live = true;
    setLoading(true);
    setError(null);
    setDone(false);
    accessApi.assignments(type, subject)
      .then(a => { if (live) { setSaved(a.profiles); setSelected(a.profiles); } })
      .catch(e => { if (live) setError((e as Error).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [type, subject]);

  const save = async (confirm = false) => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const a = await accessApi.putAssignments(type, subject, selected, confirm);
      setSaved(a.profiles);
      setSelected(a.profiles);
      setDone(true);
      setConfirmEmpty(false);
    } catch (e) {
      if (e instanceof AccessApiError && e.status === 422 && e.empty && !confirm) setConfirmEmpty(true);
      else { setConfirmEmpty(false); setError((e as Error).message); }
    } finally {
      setBusy(false);
    }
  };
  const dirty = selected.length !== saved.length || selected.some(id => !saved.includes(id));
  const toggle = (id: string, on: boolean) => { setDone(false); setSelected(on ? [...selected, id] : selected.filter(x => x !== id)); };

  return (
    <div className="space-y-4">
      <p className="text-sm text-text-secondary">
        Un sujeto puede tener varios perfiles de empresa: puede usar los modelos que permite cualquiera de ellos, siempre dentro del techo de riesgo.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SelectField label="Aplica a" value={type}
          onChange={v => { setType(v as SubjectType); setSubject(v === "tenant" ? TENANT_SUBJECT : ""); }}
          options={TYPES} />
        {type !== "tenant" && (
          <SelectField label={TYPES.find(t => t.value === type)!.label} value={subject} onChange={setSubject} options={options}
            placeholder={options.length ? "Elegí…" : "No hay elementos para elegir"} />
        )}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {done && <Notice tone="ok">Asignación guardada.</Notice>}
      {!subject ? (
        <p className="text-sm text-text-tertiary">Elegí a quién asignarle perfiles.</p>
      ) : loading ? (
        <p role="status" className="text-sm text-text-tertiary">Cargando asignación…</p>
      ) : company.length === 0 ? (
        <p className="text-sm text-text-secondary">Todavía no hay perfiles de empresa para asignar.</p>
      ) : (
        <fieldset className="space-y-2">
          <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">Perfiles de empresa</legend>
          {company.map(p => (
            <CheckField key={p.id} label={p.name} checked={selected.includes(p.id)} disabled={!ctx.perms.canAdmin || busy}
              hint={p.allows === 1 ? "Permite 1 modelo" : `Permite ${p.allows} modelos`} onChange={on => toggle(p.id, on)} />
          ))}
        </fieldset>
      )}
      {ctx.perms.canAdmin && subject && !loading && company.length > 0 && (
        <Button onClick={() => void save()} disabled={busy || !dirty}>{busy ? "Guardando…" : "Guardar asignación"}</Button>
      )}
      {confirmEmpty && (
        <ReasonDialog
          noReason
          title="Este sujeto quedaría sin modelos"
          description="Con esta asignación no podría usar ningún modelo. Confirmalo solo si es lo que querés."
          confirmLabel="Dejar sin modelos"
          danger
          onCancel={() => setConfirmEmpty(false)}
          onConfirm={() => save(true)}
        />
      )}
    </div>
  );
};
