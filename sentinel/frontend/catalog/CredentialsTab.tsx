// Pestaña «Credenciales»: lista (nombre, tipo, huella, uso), alta, reemplazo del valor y revocación.
// Write-only: el valor nunca se muestra; solo la huella. Revocar una credencial en uso exige elegir
// un reemplazo o desactivar los modelos que la usan (FR-005a).
import React, { useState } from "react";
import { Button, Card, Field, StatusBadge } from "../../../frontend/src/components/ui";
import { FieldErrors } from "../redirect/helpers";
import { EmptyRow, Notice, ReasonDialog, SelectField, tableClass, tdClass, thClass } from "../redirect/ui";
import { catalogApi } from "./api";
import {
  buildCredentialCreate, buildRevokeBody, buildSecretValue, CREDENTIAL_SHAPE_CHOICES, CredentialCreateForm,
  CredentialRow, EntryView, levelLabel, newCredentialForm, Permissions, providerOfCredential, RevokeChoice,
  valueFields,
} from "./helpers";
import { SecretFields } from "./ui";

const CreateCredential: React.FC<{ perms: Permissions; onDone: (msg: string) => void; onCancel: () => void }> = ({ perms, onDone, onCancel }) => {
  const [form, setForm] = useState<CredentialCreateForm>(newCredentialForm());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const installation = form.level === "installation";
  const provider = CREDENTIAL_SHAPE_CHOICES.find(c => c.value === form.shape)?.provider ?? null;

  const submit = async () => {
    const built = buildCredentialCreate(form, { operator: perms.operator });
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    setApiError(null);
    try {
      await catalogApi.createCredential(built.payload);
      onDone(`Credencial «${form.name.trim()}» guardada. El valor no se vuelve a mostrar.`);
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setBusy(false);
      setForm(f => ({ ...f, values: {} }));
    }
  };

  return (
    <Card title="Nueva credencial" className="mb-6">
      {apiError && <Notice tone="error" onClose={() => setApiError(null)}>{apiError}</Notice>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {perms.operator && (
          <SelectField label="Nivel" value={form.level}
            onChange={v => setForm({ ...form, level: v as CredentialCreateForm["level"], mode: "secret", values: {}, envName: "" })}
            options={[
              { value: "tenant", label: "Esta organización" },
              { value: "installation", label: "Instalación (se usa en modelos de instalación)" },
            ]} error={errors.level} />
        )}
        <Field label="Nombre" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} error={errors.name}
          hint="Para reconocerla al elegirla en un modelo." />
      </div>
      {perms.operator && installation && (
        <div className="flex flex-wrap gap-4 text-sm mt-4" role="radiogroup" aria-label="Origen del valor">
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={form.mode === "secret"} onChange={() => setForm({ ...form, mode: "secret", values: {} })} />
            Cargar el valor
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="radio" checked={form.mode === "env_ref"} onChange={() => setForm({ ...form, mode: "env_ref", values: {} })} />
            Referencia del servidor
          </label>
        </div>
      )}
      {errors.mode && <p className="text-xs text-danger mt-2">{errors.mode}</p>}
      {errors.credential && <p className="text-xs text-danger mt-2">{errors.credential}</p>}
      <div className="mt-4">
        {form.mode === "env_ref" ? (
          <Field label="Referencia del servidor" value={form.envName} onChange={e => setForm({ ...form, envName: e.target.value })}
            error={errors["cred.env"]} placeholder="REDIRECT_CRED_…"
            hint="Nombre de la variable del servidor que tiene el valor (alcanza con el sufijo)." />
        ) : (
          <div className="flex flex-col gap-3">
            <SelectField label="Forma del valor" value={form.shape}
              onChange={v => setForm({ ...form, shape: v, values: {} })}
              options={CREDENTIAL_SHAPE_CHOICES.map(c => ({ value: c.value, label: c.label }))} />
            <SecretFields fields={valueFields(provider)} values={form.values} errors={errors}
              onChange={values => setForm({ ...form, values })} />
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="secondary" onClick={onCancel}>Cancelar</Button>
        <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Guardar credencial"}</Button>
      </div>
    </Card>
  );
};

type Dialog = { kind: "replace" | "revoke"; cred: CredentialRow } | null;

export const CredentialsTab: React.FC<{
  perms: Permissions;
  credentials: CredentialRow[];
  entries: EntryView[];
  reload: () => Promise<void>;
}> = ({ perms, credentials, entries, reload }) => {
  const [creating, setCreating] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [valueErrors, setValueErrors] = useState<FieldErrors>({});
  const [choice, setChoice] = useState<RevokeChoice | "">("");
  const [replacementId, setReplacementId] = useState("");
  const [revokeErrors, setRevokeErrors] = useState<FieldErrors>({});

  const done = async (text: string) => {
    setDialog(null);
    setCreating(false);
    setMsg({ tone: "ok", text });
    await reload();
  };

  const canWrite = (c: CredentialRow) => perms.canAdmin && (c.level === "tenant" || perms.operator);

  return (
    <div>
      {msg && <Notice tone={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      {creating ? (
        <CreateCredential perms={perms} onCancel={() => setCreating(false)} onDone={done} />
      ) : perms.canAdmin && (
        <div className="flex justify-end mb-4"><Button onClick={() => setCreating(true)}>Nueva credencial</Button></div>
      )}
      <Card noPadding title="Credenciales">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Nombre</th><th className={thClass}>Tipo</th><th className={thClass}>Nivel</th>
              <th className={thClass}>Huella</th><th className={thClass}>Usada por</th><th className={thClass}>Acciones</th>
            </tr></thead>
            <tbody>
              {credentials.length === 0 && <EmptyRow cols={6}>Todavía no hay credenciales.</EmptyRow>}
              {credentials.map(c => (
                <tr key={c.id}>
                  <td className={tdClass}><div className="font-medium text-text-primary">{c.name}</div></td>
                  <td className={tdClass}>{c.kind === "env_ref" ? "Referencia del servidor" : "Valor guardado"}</td>
                  <td className={tdClass}>{levelLabel(c.level)}</td>
                  <td className={tdClass}><span className="font-mono text-xs">{c.fingerprint ?? "—"}</span></td>
                  <td className={tdClass}>
                    <StatusBadge tone={c.in_use_by.length ? "info" : "neutral"}>
                      {c.in_use_by.length === 1 ? "1 modelo" : `${c.in_use_by.length} modelos`}
                    </StatusBadge>
                    {c.in_use_by.length > 0 && <div className="text-xs text-text-tertiary mt-1">{c.in_use_by.join(", ")}</div>}
                  </td>
                  <td className={tdClass}>
                    {canWrite(c) && (
                      <div className="flex flex-wrap gap-1">
                        {c.kind === "secret" && (
                          <Button size="sm" variant="secondary" aria-label={`Reemplazar valor de ${c.name}`}
                            onClick={() => { setValues({}); setValueErrors({}); setDialog({ kind: "replace", cred: c }); }}>
                            Reemplazar valor
                          </Button>
                        )}
                        <Button size="sm" variant="danger" aria-label={`Revocar ${c.name}`}
                          onClick={() => { setChoice(""); setReplacementId(""); setRevokeErrors({}); setDialog({ kind: "revoke", cred: c }); }}>
                          Revocar
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {dialog?.kind === "replace" && (
        <ReasonDialog
          title={`Reemplazar el valor de «${dialog.cred.name}»`}
          description="El valor anterior se descarta y los modelos que la usan siguen con el nuevo. No se vuelve a mostrar."
          confirmLabel="Reemplazar" noReason
          extra={
            <SecretFields fields={valueFields(providerOfCredential(dialog.cred, entries))} values={values}
              errors={valueErrors} onChange={setValues} />
          }
          onCancel={() => { setValues({}); setDialog(null); }}
          onConfirm={async () => {
            const built = buildSecretValue(valueFields(providerOfCredential(dialog.cred, entries)), values);
            setValueErrors(built.errors);
            if (built.value === null) throw new Error(Object.keys(built.errors).length ? "Revisá los campos." : "Cargá el valor nuevo.");
            await catalogApi.replaceCredential(dialog.cred.id, built.value);
            setValues({});
            await done(`Valor de «${dialog.cred.name}» reemplazado.`);
          }}
        />
      )}
      {dialog?.kind === "revoke" && (() => {
        const inUse = dialog.cred.in_use_by.length > 0;
        const others = credentials.filter(c => c.id !== dialog.cred.id && c.level === dialog.cred.level && c.status === "active");
        return (
          <ReasonDialog
            title={`Revocar «${dialog.cred.name}»`}
            description={inUse
              ? `Está en uso por: ${dialog.cred.in_use_by.join(", ")}. Elegí qué hacer con esos modelos.`
              : "La credencial se borra y deja de poder usarse. Es definitivo."}
            confirmLabel="Revocar" danger reasonOptional
            extra={inUse ? (
              <div className="flex flex-col gap-3 mb-2" role="radiogroup" aria-label="Qué hacer con los modelos que la usan">
                <label className="inline-flex items-center gap-2 text-sm">
                  <input type="radio" name="revoke-choice" checked={choice === "replace"} onChange={() => setChoice("replace")} />
                  Pasar los modelos a otra credencial
                </label>
                {choice === "replace" && (
                  <SelectField label="Credencial de reemplazo" value={replacementId} onChange={setReplacementId}
                    options={others.map(c => ({ value: c.id, label: c.name }))}
                    placeholder={others.length ? "Elegí…" : "No hay otra credencial activa de este nivel"}
                    error={revokeErrors.replacement_id} />
                )}
                <label className="inline-flex items-center gap-2 text-sm">
                  <input type="radio" name="revoke-choice" checked={choice === "deactivate"} onChange={() => setChoice("deactivate")} />
                  Desactivar los modelos que la usan
                </label>
                {revokeErrors.choice && <p className="text-xs text-danger">{revokeErrors.choice}</p>}
              </div>
            ) : undefined}
            onCancel={() => setDialog(null)}
            onConfirm={async reason => {
              const built = buildRevokeBody(inUse, choice, replacementId, reason);
              setRevokeErrors(built.errors);
              if (!built.payload) throw new Error("Elegí qué hacer con los modelos que la usan.");
              await catalogApi.revokeCredential(dialog.cred.id, built.payload);
              await done(`Credencial «${dialog.cred.name}» revocada.`);
            }}
          />
        );
      })()}
    </div>
  );
};
