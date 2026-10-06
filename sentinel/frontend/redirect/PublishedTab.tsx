// Pestaña «Modelos publicados»: ids que ve cada herramienta, por cara y alcance.
import React, { useState } from "react";
import { Button, Card, Field } from "../../../frontend/src/components/ui";
import {
  FACES, FACE_LABELS, FAMILY_TIERS, Face, LABEL_MODES, LABEL_MODE_LABELS, LabelMode,
} from "./catalog";
import {
  buildPublishedPayload, FieldErrors, Lookups, newPublishedForm, Permissions, PublishedModel, scopeLabel,
} from "./helpers";
import { redirectApi } from "./api";
import { EmptyRow, Notice, ReasonDialog, ScopePicker, SelectField, tableClass, tdClass, thClass } from "./ui";

export const PublishedTab: React.FC<{
  perms: Permissions;
  published: PublishedModel[];
  lookups: Lookups;
  reload: () => Promise<void>;
}> = ({ perms, published, lookups, reload }) => {
  const [form, setForm] = useState(newPublishedForm());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [toDelete, setToDelete] = useState<PublishedModel | null>(null);

  const submit = async () => {
    const built = buildPublishedPayload(form);
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    try {
      await redirectApi.createPublished(built.payload);
      setMsg({ tone: "ok", text: `«${form.public_id.trim()}» publicado. Falta una regla que lo mapee a un destino.` });
      setForm(newPublishedForm());
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
      {perms.canAdmin && !open && (
        <div className="flex justify-end mb-4"><Button onClick={() => setOpen(true)}>Publicar modelo</Button></div>
      )}
      {open && (
        <Card title="Publicar un id" className="mb-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <SelectField label="Cara" value={form.face} onChange={v => setForm({ ...form, face: v as Face })}
              options={FACES.map(f => ({ value: f, label: FACE_LABELS[f] }))}
              hint="El protocolo que habla la herramienta." />
            <Field label="Id publicado" value={form.public_id} onChange={e => setForm({ ...form, public_id: e.target.value })}
              error={errors.public_id} hint="Lo que la herramienta pide y ve en su lista de modelos." />
            {form.face === "claude" && (
              <SelectField label="Tier" value={form.family_tier}
                onChange={v => setForm({ ...form, family_tier: v as typeof form.family_tier })}
                options={FAMILY_TIERS.map(t => ({ value: t, label: t }))} placeholder="Elegí…" error={errors.family_tier} />
            )}
            {form.face === "claude" && (
              <label className="inline-flex items-center gap-2 text-sm self-end pb-2">
                <input type="checkbox" checked={form.is_family_default}
                  onChange={e => setForm({ ...form, is_family_default: e.target.checked })} />
                Id por defecto de este tier
              </label>
            )}
            <SelectField label="Etiqueta" value={form.label_mode}
              onChange={v => setForm({ ...form, label_mode: v as LabelMode })}
              options={LABEL_MODES.map(m => ({ value: m, label: LABEL_MODE_LABELS[m] }))} />
            {form.label_mode === "custom" && (
              <Field label="Texto de la etiqueta" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} error={errors.label} />
            )}
            <Field label="Modelo de referencia (opcional)" value={form.reference_model}
              onChange={e => setForm({ ...form, reference_model: e.target.value })}
              hint="Para comparar costos contra el modelo que se habría usado." />
          </div>
          <div className="mt-4">
            <ScopePicker type={form.scope_type} value={form.scope_value} lookups={lookups} error={errors.scope_value}
              onChange={(scope_type, scope_value) => setForm({ ...form, scope_type, scope_value })} />
          </div>
          <div className="flex justify-end gap-2 mt-5">
            <Button variant="secondary" onClick={() => { setOpen(false); setErrors({}); }}>Cancelar</Button>
            <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Publicar"}</Button>
          </div>
        </Card>
      )}
      <Card noPadding title="Ids publicados">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Cara</th><th className={thClass}>Id</th><th className={thClass}>Tier</th>
              <th className={thClass}>Etiqueta</th><th className={thClass}>Alcance</th><th className={thClass}></th>
            </tr></thead>
            <tbody>
              {published.length === 0 && <EmptyRow cols={6}>Ningún id publicado todavía.</EmptyRow>}
              {published.map(p => (
                <tr key={p.id}>
                  <td className={tdClass}>{FACE_LABELS[p.face] ?? p.face}</td>
                  <td className={tdClass}><span className="font-mono">{p.public_id}</span></td>
                  <td className={tdClass}>{p.family_tier ?? "—"}{p.is_family_default ? " (por defecto)" : ""}</td>
                  <td className={tdClass}>{p.label_mode === "custom" ? p.label : LABEL_MODE_LABELS[p.label_mode]}</td>
                  <td className={tdClass}>{scopeLabel(p.scope_type, p.scope_value, lookups)}</td>
                  <td className={tdClass}>
                    {perms.canAdmin && <Button size="sm" variant="danger" onClick={() => setToDelete(p)}>Borrar</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {toDelete && (
        <ReasonDialog
          title={`Borrar «${toDelete.public_id}»`}
          description="También se borran las reglas que lo mapean. Las herramientas que lo pidan recibirán «modelo no disponible»."
          confirmLabel="Borrar" danger noReason
          onCancel={() => setToDelete(null)}
          onConfirm={async () => {
            await redirectApi.deletePublished(toDelete.id);
            setToDelete(null);
            setMsg({ tone: "ok", text: `«${toDelete.public_id}» borrado.` });
            await reload();
          }}
        />
      )}
    </div>
  );
};
