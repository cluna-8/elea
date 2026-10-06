// Pestaña «Reglas»: id publicado (o tier) + clase de pedido opcional → destinos en orden
// (el primero elegible sirve; el resto son fallbacks).
import React, { useState } from "react";
import { Button, Card } from "../../../frontend/src/components/ui";
import { FACE_LABELS, FAMILY_TIERS, REQUEST_CLASSES, REQUEST_CLASS_LABELS } from "./catalog";
import {
  buildRulePayload, Destination, destinationStatus, FieldErrors, Lookups, moveItem, newRuleForm, Permissions,
  PublishedModel, publishedLabel, Rule, scopeLabel,
} from "./helpers";
import { redirectApi } from "./api";
import { EmptyRow, Notice, ReasonDialog, ScopePicker, SelectField, tableClass, tdClass, thClass } from "./ui";

export const RulesTab: React.FC<{
  perms: Permissions;
  rules: Rule[];
  published: PublishedModel[];
  destinations: Destination[];
  lookups: Lookups;
  reload: () => Promise<void>;
}> = ({ perms, rules, published, destinations, lookups, reload }) => {
  const [form, setForm] = useState(newRuleForm());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pick, setPick] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [toDelete, setToDelete] = useState<Rule | null>(null);

  const destName = (id: string, rule?: Rule) => {
    const found = destinations.find(d => d.id === id);
    if (found) return found.name;
    const w = rule?.warnings?.find(x => x.destination_id === id);
    return w?.code === "offer_withdrawn" ? "(oferta retirada: ya no se ofrece a tu organización)" : "(destino no disponible)";
  };
  const pubName = (id: string | null) => {
    const p = published.find(x => x.id === id);
    return p ? `${FACE_LABELS[p.face]} · ${publishedLabel(p)}` : "(id borrado)";
  };
  // La lista ya viene del catálogo (activos, de texto, visibles); un bloqueado por defecto se ofrece marcado.
  const usable = destinations.filter(d => d.status === "active" && !form.targets.includes(d.id));

  const submit = async () => {
    const built = buildRulePayload(form);
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    try {
      await redirectApi.createRule(built.payload);
      setMsg({ tone: "ok", text: "Regla creada." });
      setForm(newRuleForm());
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
        <div className="flex justify-end mb-4"><Button onClick={() => setOpen(true)}>Nueva regla</Button></div>
      )}
      {open && (
        <Card title="Nueva regla" className="mb-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <SelectField label="Se aplica a" value={form.by}
              onChange={v => setForm({ ...form, by: v as "published" | "tier" })}
              options={[{ value: "published", label: "Un id publicado" }, { value: "tier", label: "Todo un tier (familia Claude)" }]} />
            {form.by === "published" ? (
              <SelectField label="Id publicado" value={form.published_model_id}
                onChange={v => setForm({ ...form, published_model_id: v })}
                options={published.map(p => ({ value: p.id, label: `${FACE_LABELS[p.face]} · ${publishedLabel(p)} — ${scopeLabel(p.scope_type, p.scope_value, lookups)}` }))}
                placeholder={published.length ? "Elegí…" : "Primero publicá un id"} error={errors.published_model_id} />
            ) : (
              <SelectField label="Tier" value={form.family_tier}
                onChange={v => setForm({ ...form, family_tier: v as typeof form.family_tier })}
                options={FAMILY_TIERS.map(t => ({ value: t, label: t }))} placeholder="Elegí…" error={errors.family_tier} />
            )}
            <SelectField label="Clase de pedido" value={form.request_class}
              onChange={v => setForm({ ...form, request_class: v as typeof form.request_class })}
              options={REQUEST_CLASSES.map(c => ({ value: c, label: REQUEST_CLASS_LABELS[c] }))}
              placeholder="Todas (regla general)" />
          </div>
          <div className="mt-4">
            <ScopePicker type={form.scope_type} value={form.scope_value} lookups={lookups} error={errors.scope_value}
              onChange={(scope_type, scope_value) => setForm({ ...form, scope_type, scope_value })} />
          </div>
          <div className="mt-5">
            <h4 className="text-sm font-semibold text-text-primary mb-2">Destinos en orden</h4>
            <ol className="flex flex-col gap-2 mb-3" aria-label="Destinos en orden">
              {form.targets.map((id, i) => (
                <li key={id} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
                  <span><span className="text-text-tertiary mr-2">{i === 0 ? "Principal" : `Alternativa ${i}`}</span>{destName(id)}</span>
                  <span className="flex gap-1">
                    <Button size="sm" variant="ghost" aria-label="Subir" disabled={i === 0}
                      onClick={() => setForm({ ...form, targets: moveItem(form.targets, i, -1) })}>↑</Button>
                    <Button size="sm" variant="ghost" aria-label="Bajar" disabled={i === form.targets.length - 1}
                      onClick={() => setForm({ ...form, targets: moveItem(form.targets, i, 1) })}>↓</Button>
                    <Button size="sm" variant="ghost" onClick={() => setForm({ ...form, targets: form.targets.filter(t => t !== id) })}>Quitar</Button>
                  </span>
                </li>
              ))}
            </ol>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <SelectField label="Agregar destino" value={pick} onChange={setPick}
                  options={usable.map(d => ({ value: d.id, label: destinationStatus(d).label === "Activo" ? d.name : `${d.name} (${destinationStatus(d).label.toLowerCase()})` }))}
                  placeholder={usable.length ? "Elegí…" : "No quedan destinos para agregar"} error={errors.targets} />
              </div>
              <Button variant="secondary" disabled={!pick}
                onClick={() => { setForm({ ...form, targets: [...form.targets, pick] }); setPick(""); }}>Agregar</Button>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-5">
            <Button variant="secondary" onClick={() => { setOpen(false); setErrors({}); }}>Cancelar</Button>
            <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Crear regla"}</Button>
          </div>
        </Card>
      )}
      <Card noPadding title="Reglas">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Modelo</th><th className={thClass}>Clase</th><th className={thClass}>Alcance</th>
              <th className={thClass}>Destinos (en orden)</th><th className={thClass}></th>
            </tr></thead>
            <tbody>
              {rules.length === 0 && <EmptyRow cols={5}>Sin reglas: los ids publicados responden «modelo no disponible».</EmptyRow>}
              {rules.map(r => (
                <tr key={r.id}>
                  <td className={tdClass}>{r.published_model_id ? pubName(r.published_model_id) : `Tier ${r.family_tier}`}</td>
                  <td className={tdClass}>{r.request_class ? REQUEST_CLASS_LABELS[r.request_class] : "Todas"}</td>
                  <td className={tdClass}>{scopeLabel(r.scope_type, r.scope_value, lookups)}</td>
                  <td className={tdClass}>
                    <ol className="list-decimal list-inside">
                      {r.targets.map(t => <li key={t}>{destName(t, r)}</li>)}
                    </ol>
                  </td>
                  <td className={tdClass}>
                    {perms.canAdmin && <Button size="sm" variant="danger" onClick={() => setToDelete(r)}>Borrar</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {toDelete && (
        <ReasonDialog
          title="Borrar la regla"
          description="Los pedidos que caían en esta regla pasan a la siguiente que aplique, o reciben «modelo no disponible»."
          confirmLabel="Borrar" danger noReason
          onCancel={() => setToDelete(null)}
          onConfirm={async () => {
            await redirectApi.deleteRule(toDelete.id);
            setToDelete(null);
            setMsg({ tone: "ok", text: "Regla borrada." });
            await reload();
          }}
        />
      )}
    </div>
  );
};
