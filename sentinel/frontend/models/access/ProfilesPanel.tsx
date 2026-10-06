// «Perfiles»: lista con tipo, reglas legibles y cuántos modelos permite cada uno; alta, edición y archivo.
import React, { useMemo, useState } from "react";
import { Button, Field, StatusBadge } from "../../../../frontend/src/components/ui";
import { Modal, ModalButtons } from "../../catalog/ui";
import { Notice, ReasonDialog, SelectField } from "../../redirect/ui";
import { accessApi, AccessApiError, Profile, ProfileKind, ProfileRule } from "../accessApi";
import { RuleEditor } from "./RuleEditor";
import { allowsLabel, canWriteKind, describeRule, KIND_LABELS, validateRules } from "./helpers";
import type { AccessCtx } from "./types";

const msg = (e: unknown) => (e instanceof Error ? e.message : "No se pudo completar la acción.");

const ProfileForm: React.FC<{ ctx: AccessCtx; profile: Profile | null; onClose: () => void; onSaved: () => void }> = ({ ctx, profile, onClose, onSaved }) => {
  const kinds = (["company", "ceiling", "key"] as ProfileKind[]).filter(k => canWriteKind(ctx.perms, k));
  const [kind, setKind] = useState<ProfileKind>(profile?.kind ?? kinds[0]);
  const [name, setName] = useState(profile?.name ?? "");
  const [rules, setRules] = useState<ProfileRule[]>(profile?.rules ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const problem = !name.trim() ? "Escribí un nombre para el perfil." : validateRules(rules);
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError(null);
    try {
      if (profile) await accessApi.patchProfile(profile.id, { name: name.trim(), rules });
      else await accessApi.createProfile({ kind, name: name.trim(), rules });
      onSaved();
    } catch (e) {
      setError(msg(e));
      setBusy(false);
    }
  };

  return (
    <Modal title={profile ? "Editar perfil" : "Nuevo perfil"} onClose={onClose}
      footer={<ModalButtons onCancel={onClose} onSubmit={() => void submit()} busy={busy} submitLabel={profile ? "Guardar" : "Crear perfil"} />}>
      <div className="flex flex-col gap-4">
        {error && <Notice tone="error">{error}</Notice>}
        {!profile && (
          <SelectField label="Tipo" value={kind} onChange={v => setKind(v as ProfileKind)}
            options={kinds.map(k => ({ value: k, label: KIND_LABELS[k] }))} />
        )}
        <Field label="Nombre" value={name} onChange={e => setName(e.target.value)} autoComplete="off" />
        <RuleEditor rules={rules} onChange={setRules} entries={ctx.entries} />
      </div>
    </Modal>
  );
};

export const ProfilesPanel: React.FC<{ ctx: AccessCtx }> = ({ ctx }) => {
  const [showArchived, setShowArchived] = useState(false);
  const [form, setForm] = useState<{ profile: Profile | null } | null>(null);
  const [archiving, setArchiving] = useState<Profile | null>(null);
  const names = useMemo(() => new Map(ctx.entries.map(e => [e.id, e.name])), [ctx.entries]);
  const rows = ctx.profiles.filter(p => showArchived || !p.archived);
  const canCreate = ctx.perms.canAdmin || ctx.perms.canCeiling;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="inline-flex items-center gap-2 text-sm text-text-primary">
          <input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />
          Ver archivados
        </label>
        {canCreate && <Button onClick={() => setForm({ profile: null })}>Nuevo perfil</Button>}
      </div>
      {rows.length === 0 ? (
        <p className="rounded-md border border-border px-4 py-8 text-center text-sm text-text-secondary">Todavía no hay perfiles.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map(p => (
            <li key={p.id} className="rounded-md border border-border bg-surface px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-text-primary">{p.name}</span>
                    <StatusBadge tone="info">{KIND_LABELS[p.kind]}</StatusBadge>
                    {p.seeded && <StatusBadge tone="neutral">Sembrado</StatusBadge>}
                    {p.archived && <StatusBadge tone="warn">Archivado</StatusBadge>}
                  </div>
                  <span className="block text-xs text-text-secondary">{allowsLabel(p.allows)}</span>
                </div>
                {canWriteKind(ctx.perms, p.kind) && !p.archived && (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => setForm({ profile: p })}>Editar</Button>
                    <Button variant="ghost" aria-label={`Archivar ${p.name}`} onClick={() => setArchiving(p)}>Archivar</Button>
                  </div>
                )}
              </div>
              {p.rules.length > 0 ? (
                <ul className="mt-2 list-disc pl-5 text-xs text-text-secondary">
                  {p.rules.map((r, i) => <li key={i}>{describeRule(r, id => names.get(id))}</li>)}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-text-tertiary">Sin reglas.</p>
              )}
            </li>
          ))}
        </ul>
      )}
      {form && (
        <ProfileForm ctx={ctx} profile={form.profile} onClose={() => setForm(null)}
          onSaved={() => { setForm(null); void ctx.reload(); }} />
      )}
      {archiving && (
        <ReasonDialog
          title={`Archivar «${archiving.name}»`}
          description="Sale de los selectores y queda como evidencia. Si algún sujeto lo tiene asignado, primero hay que quitárselo."
          confirmLabel="Archivar"
          danger
          onCancel={() => setArchiving(null)}
          onConfirm={async reason => {
            try { await accessApi.archiveProfile(archiving.id, reason); }
            catch (e) { throw e instanceof AccessApiError ? e : new Error(msg(e)); }
            setArchiving(null);
            void ctx.reload();
          }}
        />
      )}
    </div>
  );
};
