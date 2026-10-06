// Formulario de modelo (alta y edición): proveedor, modelo real, protocolo, capacidad, capacidades
// funcionales y credencial (existente, nueva o referencia del servidor). La credencial es write-only.
import React from "react";
import { Field } from "../../../frontend/src/components/ui";
import {
  PROTOCOL_FAMILIES, PROTOCOL_LABELS, PROVIDERS, PROVIDER_LABELS, Provider, ProtocolFamily,
} from "../redirect/catalog";
import { FieldErrors } from "../redirect/helpers";
import { SelectField } from "../redirect/ui";
import {
  Capability, CAPABILITIES, CAPABILITY_LABELS, changesSheetSubject, credentialOptionLabel, CredentialRow,
  CredMode, defaultAggregator, EntryForm as Form, EntryLevel, EntryRole, EntryView, FEATURE_LABELS, FEATURES,
  levelLabel, needsApiBase, Permissions, ROLE_LABELS, ROLES, valueFields, withLevel, withProvider,
} from "./helpers";
import { CheckField, SecretFields } from "./ui";

export const EntryFormFields: React.FC<{
  form: Form;
  setForm: (f: Form) => void;
  errors: FieldErrors;
  perms: Permissions;
  /** Edición: la entrada original (nivel fijo, credencial actual, aviso de ficha). */
  entry?: EntryView;
  credentials: CredentialRow[];
}> = ({ form, setForm, errors, perms, entry, credentials }) => {
  const editing = Boolean(entry);
  const installation = form.level === "installation";
  const fields = valueFields(form.provider);
  const optionalSecret = !fields.some(f => f.required);
  const usable = credentials.filter(c => c.status === "active" && c.level === form.level);
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const modes: { mode: CredMode; label: string; show: boolean }[] = [
    { mode: "keep", label: "Mantener la actual", show: editing && Boolean(entry?.has_credential) },
    { mode: "existing", label: "Usar una credencial existente", show: true },
    { mode: "new", label: "Cargar una credencial nueva", show: true },
    { mode: "env", label: "Referencia del servidor", show: perms.operator && installation },
    { mode: "none", label: "Sin credencial", show: optionalSecret || (editing && !entry?.has_credential) },
  ];

  return (
    <div className="flex flex-col gap-5">
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {!editing && perms.operator && (
          <SelectField
            label="Nivel"
            value={form.level}
            onChange={v => setForm(withLevel(form, v as EntryLevel))}
            options={(["tenant", "installation"] as EntryLevel[]).map(l => ({
              value: l,
              label: l === "tenant" ? "Esta organización (clave propia)" : "Instalación (se ofrece a organizaciones)",
            }))}
            error={errors.level}
          />
        )}
        {editing && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Nivel</span>
            <span className="text-sm text-text-primary">{levelLabel(form.level)}</span>
          </div>
        )}
        <Field label="Nombre" value={form.name} onChange={e => set({ name: e.target.value })} error={errors.name}
          hint="Nombre neutro que ven las personas administradoras." />
        <Field label={editing ? "Id público" : "Id público (opcional)"} value={form.public_id}
          onChange={e => set({ public_id: e.target.value })} error={errors.public_id}
          placeholder={editing ? undefined : "Se genera a partir del nombre"}
          hint="Lo usan Hub y otras herramientas para pedir el modelo. Sin espacios." />
        <SelectField
          label="Proveedor"
          value={form.provider}
          onChange={v => setForm(withProvider(form, v as Provider))}
          options={PROVIDERS.map(p => ({ value: p, label: PROVIDER_LABELS[p] }))}
          hint={form.provider === "deepseek" ? "Queda bloqueado hasta que cumplimiento lo habilite." : undefined}
        />
        <Field label="Modelo real" value={form.real_model} onChange={e => set({ real_model: e.target.value })}
          error={errors.real_model} hint="El nombre exacto del modelo en el proveedor." />
        <SelectField
          label="Familia de protocolo"
          value={form.protocol_family}
          onChange={v => set({ protocol_family: v as ProtocolFamily })}
          options={PROTOCOL_FAMILIES.map(p => ({ value: p, label: PROTOCOL_LABELS[p] }))}
          hint="Sugerida según el proveedor."
        />
        <Field
          label={needsApiBase(form.provider) ? "Dirección base" : "Dirección base (opcional)"}
          value={form.api_base}
          onChange={e => set({ api_base: e.target.value })}
          error={errors.api_base}
          placeholder="https://…"
        />
        <SelectField label="Uso" value={form.role} onChange={v => set({ role: v as EntryRole })}
          options={ROLES.map(r => ({ value: r, label: ROLE_LABELS[r] }))} />
        <SelectField label="Capacidad" value={form.capability} onChange={v => set({ capability: v as Capability })}
          options={CAPABILITIES.map(c => ({ value: c, label: CAPABILITY_LABELS[c] }))}
          hint="Pequeño, estándar o frontera: ordena la lista y las reglas por perfil." />
        <Field label="Ventana de contexto (tokens, opcional)" value={form.context_window} inputMode="numeric"
          onChange={e => set({ context_window: e.target.value })} error={errors.context_window} placeholder="128000" />
        <Field label="Salida máxima (tokens, opcional)" value={form.max_output} inputMode="numeric"
          onChange={e => set({ max_output: e.target.value })} error={errors.max_output} placeholder="8192" />
      </div>

      <CheckField
        label="Es un agregador"
        checked={form.aggregator}
        onChange={v => set({ aggregator: v })}
        hint={defaultAggregator(form.provider)
          ? "Este proveedor enruta a terceros: queda marcado como agregador y no cubre al proveedor final."
          : "Marcalo si este proveedor enruta a terceros: la ficha solo cubre su capa."}
      />

      <fieldset>
        <legend className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">Capacidades funcionales</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {FEATURES.map(f => (
            <CheckField key={f} label={FEATURE_LABELS[f]} checked={form.features[f]}
              onChange={v => set({ features: { ...form.features, [f]: v } })} />
          ))}
        </div>
      </fieldset>

      <Field
        label="Parámetros no soportados"
        value={form.unsupported}
        onChange={e => set({ unsupported: e.target.value })}
        error={errors.unsupported_params}
        placeholder="temperature, top_p"
        hint="Opcional. Parámetros del pedido que este modelo rechaza: Sentinel los quita antes de llegar al proveedor y deja constancia de sus nombres en la auditoría."
      />

      <fieldset>
        <legend className="text-sm font-semibold text-text-primary mb-2">Credencial</legend>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm mb-3" role="radiogroup" aria-label="Origen de la credencial">
          {modes.filter(m => m.show).map(m => (
            <label key={m.mode} className="inline-flex items-center gap-2">
              <input type="radio" name="cred-mode" checked={form.credMode === m.mode}
                onChange={() => set({ credMode: m.mode })} />
              {m.label}
            </label>
          ))}
        </div>
        {errors.credential && <p className="text-xs text-danger mb-2">{errors.credential}</p>}
        {form.credMode === "keep" && entry?.credential && (
          <p className="text-sm text-text-secondary">
            Credencial actual: {entry.credential.name} · huella {entry.credential.fingerprint ?? "—"}. El valor no se muestra.
          </p>
        )}
        {form.credMode === "existing" && (
          <SelectField
            label="Credencial"
            value={form.credentialId}
            onChange={v => set({ credentialId: v })}
            options={usable.map(c => ({ value: c.id, label: credentialOptionLabel(c) }))}
            placeholder={usable.length ? "Elegí…" : "No hay credenciales de este nivel"}
          />
        )}
        {form.credMode === "new" && (
          <div className="flex flex-col gap-3">
            <Field label="Nombre de la credencial" value={form.newName} onChange={e => set({ newName: e.target.value })}
              hint="Para reconocerla después; el valor no vuelve a mostrarse." />
            <SecretFields fields={fields} values={form.values} errors={errors} onChange={values => set({ values })} />
          </div>
        )}
        {form.credMode === "env" && (
          <div className="flex flex-col gap-2">
            <Field label="Referencia del servidor" value={form.envRef} onChange={e => set({ envRef: e.target.value })}
              error={errors["cred.env"]} placeholder="REDIRECT_CRED_…"
              hint="Nombre de la variable del servidor que tiene el valor (alcanza con el sufijo). El valor nunca pasa por la consola." />
          </div>
        )}
        {form.credMode === "none" && <p className="text-sm text-text-tertiary">Este modelo se usa sin credencial.</p>}
      </fieldset>

      {entry && changesSheetSubject(form, entry) && (
        <p role="status" className="text-sm text-warn">
          Cambiar el proveedor o el modelo real deja la ficha de cumplimiento desactualizada: hay que revisarla y guardarla de nuevo.
        </p>
      )}
    </div>
  );
};
