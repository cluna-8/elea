// Pestaña «Política»: estado apagada / encendida por alcance, con motivo (el estado «sombra» no se ofrece en el MVP, FR-010).
import React, { useState } from "react";
import { Button, Card, Field, StatusBadge } from "../../../frontend/src/components/ui";
import { OFFERED_POLICY_STATES, POLICY_STATE_LABELS, PolicyState, ScopeType } from "./catalog";
import { buildPolicyRequest, FieldErrors, Lookups, Permissions, PolicyRow, scopeLabel } from "./helpers";
import { redirectApi } from "./api";
import { EmptyRow, Notice, ScopePicker, SelectField, tableClass, tdClass, thClass } from "./ui";

const TONE: Record<PolicyState, "neutral" | "info" | "ok"> = { off: "neutral", shadow: "info", on: "ok" };

export const PolicyTab: React.FC<{
  perms: Permissions;
  policy: PolicyRow[];
  lookups: Lookups;
  reload: () => Promise<void>;
}> = ({ perms, policy, lookups, reload }) => {
  const [form, setForm] = useState<{ scope_type: ScopeType; scope_value: string; state: PolicyState; reason: string }>(
    { scope_type: "tenant", scope_value: "", state: "off", reason: "" });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const submit = async () => {
    const built = buildPolicyRequest(form);
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    try {
      await redirectApi.putPolicy(built.payload.path, built.payload.body);
      setMsg({ tone: "ok", text: `Política ${POLICY_STATE_LABELS[form.state].toLowerCase()} para ${scopeLabel(form.scope_type, form.scope_value || "*", lookups).toLowerCase()}.` });
      setForm({ ...form, reason: "" });
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
      <Notice tone="info">
        Sin ninguna fila la política está apagada. Gana el alcance más específico (conexión, usuario,
        grupo, organización).
      </Notice>
      {perms.canAdmin && (
        <Card title="Cambiar el estado" className="mb-6">
          <ScopePicker type={form.scope_type} value={form.scope_value} lookups={lookups} error={errors.scope_value}
            onChange={(scope_type, scope_value) => setForm({ ...form, scope_type, scope_value })} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <SelectField label="Estado" value={form.state} onChange={v => setForm({ ...form, state: v as PolicyState })}
              options={OFFERED_POLICY_STATES.map(s => ({ value: s, label: POLICY_STATE_LABELS[s] }))} />
            <Field label="Motivo" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} error={errors.reason} />
          </div>
          <div className="flex justify-end mt-4">
            <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Guardar estado"}</Button>
          </div>
        </Card>
      )}
      <Card noPadding title="Estado por alcance">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Alcance</th><th className={thClass}>Estado</th>
              <th className={thClass}>Motivo</th><th className={thClass}>Cambio</th>
            </tr></thead>
            <tbody>
              {policy.length === 0 && <EmptyRow cols={4}>Apagada en toda la organización.</EmptyRow>}
              {policy.map(p => (
                <tr key={p.id}>
                  <td className={tdClass}>{scopeLabel(p.scope_type, p.scope_value, lookups)}</td>
                  <td className={tdClass}><StatusBadge tone={TONE[p.state]} dot>{POLICY_STATE_LABELS[p.state]}</StatusBadge></td>
                  <td className={tdClass}>{p.reason ?? "—"}</td>
                  <td className={tdClass}>{p.changed_at ? new Date(p.changed_at).toLocaleString("es") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
