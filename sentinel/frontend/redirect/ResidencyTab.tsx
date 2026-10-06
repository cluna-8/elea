// Pestaña «Residencia»: posturas por alcance (rige la más restrictiva) y postura efectiva.
import React, { useState } from "react";
import { Button, Card, Field, StatusBadge, cn } from "../../../frontend/src/components/ui";
import { JURISDICTIONS, POSTURE_MODES, POSTURE_MODE_LABELS, PostureMode } from "./catalog";
import {
  buildPosturePayload, FieldErrors, Lookups, newPostureForm, Permissions, PostureRow, scopeLabel,
} from "./helpers";
import { redirectApi } from "./api";
import { EmptyRow, Notice, ReasonDialog, ScopePicker, SelectField, tableClass, tdClass, thClass } from "./ui";

export interface EffectivePosture { mode: string; jurisdictions: string[]; explicit: boolean }

const modeLabel = (m: string) => POSTURE_MODE_LABELS[m as PostureMode] ?? m;

export const JurisdictionPicker: React.FC<{ value: string[]; onChange: (v: string[]) => void; error?: string }> = ({ value, onChange, error }) => (
  <fieldset>
    <legend className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-1.5">Jurisdicciones permitidas</legend>
    <div className="flex flex-wrap gap-2">
      {JURISDICTIONS.map(j => {
        const on = value.includes(j.code);
        return (
          <label key={j.code} title={j.label}
            className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs cursor-pointer",
              on ? "border-primary bg-primary-tint text-text-primary" : "border-border text-text-secondary")}>
            <input type="checkbox" className="sr-only" checked={on}
              onChange={() => onChange(on ? value.filter(v => v !== j.code) : [...value, j.code])} />
            {j.code} · {j.label}
          </label>
        );
      })}
    </div>
    {error && <p className="text-xs text-danger mt-1">{error}</p>}
  </fieldset>
);

export const ResidencyTab: React.FC<{
  perms: Permissions;
  postures: PostureRow[];
  effective: EffectivePosture | null;
  lookups: Lookups;
  reload: () => Promise<void>;
}> = ({ perms, postures, effective, lookups, reload }) => {
  const [form, setForm] = useState(newPostureForm());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [toDelete, setToDelete] = useState<PostureRow | null>(null);

  const submit = async () => {
    const built = buildPosturePayload(form, perms);
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    try {
      await redirectApi.createPosture(built.payload);
      setMsg({ tone: "ok", text: "Postura agregada." });
      setForm(newPostureForm());
      setOpen(false);
      await reload();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {msg && <Notice tone={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      {effective && (
        <Card title="Postura efectiva para pedidos redirigidos (toda la organización)" className="mb-6">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <StatusBadge tone={effective.mode === "off" ? "warn" : "info"} dot>{modeLabel(effective.mode)}</StatusBadge>
            {effective.jurisdictions.length > 0 && <span>Jurisdicciones: <b>{effective.jurisdictions.join(", ")}</b></span>}
            <span className="text-text-tertiary">
              {effective.explicit ? "Surge de las filas cargadas." : "Por defecto: solo la región de la organización."}
            </span>
          </div>
        </Card>
      )}
      {perms.canAddPosture && !open && (
        <div className="flex justify-end mb-4"><Button onClick={() => setOpen(true)}>Agregar postura</Button></div>
      )}
      {open && (
        <Card title="Nueva postura" className="mb-6">
          {!perms.canManagePosture && (
            <Notice tone="info">
              Como administrador podés agregar posturas (nunca relajan: rige la más restrictiva).
              Editar o borrar es de cumplimiento.
            </Notice>
          )}
          <ScopePicker type={form.scope_type} value={form.scope_value} lookups={lookups} error={errors.scope_value}
            onChange={(scope_type, scope_value) => setForm({ ...form, scope_type, scope_value })} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <SelectField label="Modo" value={form.mode} onChange={v => setForm({ ...form, mode: v as PostureMode })}
              options={POSTURE_MODES.map(m => ({ value: m, label: POSTURE_MODE_LABELS[m] }))} />
            <Field label="Motivo" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} error={errors.reason} />
          </div>
          {form.mode !== "off" && (
            <div className="mt-4">
              <JurisdictionPicker value={form.jurisdictions} onChange={jurisdictions => setForm({ ...form, jurisdictions })} error={errors.jurisdictions} />
            </div>
          )}
          {perms.canManagePosture && (
            <label className="inline-flex items-center gap-2 text-sm mt-4">
              <input type="checkbox" checked={form.accept_foreign_entity}
                onChange={e => setForm({ ...form, accept_foreign_entity: e.target.checked })} />
              Aceptar destinos que infieren en región pero cuya entidad es de otra jurisdicción
            </label>
          )}
          {errors.accept_foreign_entity && <p className="text-xs text-danger mt-1">{errors.accept_foreign_entity}</p>}
          <div className="flex justify-end gap-2 mt-5">
            <Button variant="secondary" onClick={() => { setOpen(false); setErrors({}); }}>Cancelar</Button>
            <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Agregar"}</Button>
          </div>
        </Card>
      )}
      <Card noPadding title="Posturas cargadas">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Alcance</th><th className={thClass}>Modo</th><th className={thClass}>Jurisdicciones</th>
              <th className={thClass}>Motivo</th><th className={thClass}>Cargada por</th><th className={thClass}></th>
            </tr></thead>
            <tbody>
              {postures.length === 0 && <EmptyRow cols={6}>Sin posturas explícitas.</EmptyRow>}
              {postures.map(p => (
                <tr key={p.id}>
                  <td className={tdClass}>{scopeLabel(p.scope_type, p.scope_value, lookups)}</td>
                  <td className={tdClass}>{modeLabel(p.mode)}{p.accept_foreign_entity ? " · acepta entidad de otra jurisdicción" : ""}</td>
                  <td className={tdClass}>{p.jurisdictions.length ? p.jurisdictions.join(", ") : "—"}</td>
                  <td className={tdClass}>{p.reason}</td>
                  <td className={tdClass}>{p.created_by_role === "compliance_officer" ? "Cumplimiento" : p.created_by_role === "super_admin" ? "Super-admin" : "Administración"}</td>
                  <td className={tdClass}>
                    {perms.canManagePosture && <Button size="sm" variant="danger" onClick={() => setToDelete(p)}>Borrar</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {toDelete && (
        <ReasonDialog
          title="Borrar la postura"
          description="Borrar una postura puede relajar la residencia. Queda registrado con tu motivo."
          confirmLabel="Borrar" danger
          onCancel={() => setToDelete(null)}
          onConfirm={async reason => {
            await redirectApi.deletePosture(toDelete.id, reason);
            setToDelete(null);
            setMsg({ tone: "ok", text: "Postura borrada." });
            await reload();
          }}
        />
      )}
    </div>
  );
};
