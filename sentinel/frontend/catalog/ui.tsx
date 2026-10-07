// Piezas propias de la pantalla: insignia de semáforo con motivos, modal ancho y campos de credencial.
// Todo sobre el kit de la consola (tokens 029), sin estilos propios.
import React, { useEffect, useId } from "react";
import { Button, Field, StatusBadge, cn, inputBaseClass } from "../../../frontend/src/components/ui";
import type { CredentialFieldSpec, FieldErrors } from "../redirect/helpers";
import {
  apiVersionBelowResponsesFloor, AZURE_RESPONSES_MIN_API_VERSION, motivoLabel, semaforoLabel, SEMAFORO_TONES, Semaforo,
} from "./helpers";

/** Insignia del semáforo; con `detail`, lista los motivos en castellano debajo. */
export const SemaforoBadge: React.FC<{ semaforo: Semaforo; detail?: boolean; regionLabel?: string | null }> = ({ semaforo, detail, regionLabel }) => {
  const estado = semaforo?.estado ?? "unclassified";
  const label = semaforoLabel(semaforo, regionLabel);
  const motivos = semaforo?.motivos ?? [];
  return (
    <div className="flex flex-col gap-1">
      <StatusBadge tone={SEMAFORO_TONES[estado]} dot aria-label={`Semáforo: ${label}`}>
        {label}
      </StatusBadge>
      {motivos.length > 0 && (
        detail ? (
          <ul className="list-disc pl-5 text-xs text-text-secondary">
            {motivos.map(m => <li key={m}>{motivoLabel(m)}</li>)}
          </ul>
        ) : (
          <div className="text-xs text-text-tertiary">{motivos.map(motivoLabel).join(" · ")}</div>
        )
      )}
    </div>
  );
};

/** Diálogo ancho con scroll interno y pie propio (alta/edición, ficha). */
export const Modal: React.FC<{
  title: string;
  onClose: () => void;
  footer?: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, onClose, footer, children }) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-card bg-surface shadow-card border border-border">
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
          <h3 className="text-[15px] font-semibold text-text-primary">{title}</h3>
          <button type="button" className="text-xs underline text-text-secondary" onClick={onClose}>Cerrar</button>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
};

export const CheckField: React.FC<{
  label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; hint?: string;
}> = ({ label, checked, onChange, disabled, hint }) => {
  const id = useId();
  return (
    <div className="flex flex-col gap-0.5">
      <label htmlFor={id} className="inline-flex items-center gap-2 text-sm text-text-primary">
        <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />
        {label}
      </label>
      {hint && <span className="pl-6 text-xs text-text-tertiary">{hint}</span>}
    </div>
  );
};

/** Campos del valor de una credencial (write-only: siempre vacíos, tipo contraseña). */
export const SecretFields: React.FC<{
  fields: CredentialFieldSpec[];
  values: Record<string, string>;
  errors: FieldErrors;
  onChange: (values: Record<string, string>) => void;
}> = ({ fields, values, errors, onChange }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
    {fields.map(f => {
      const err = errors[`cred.${f.name}`];
      const set = (v: string) => onChange({ ...values, [f.name]: v });
      const label = f.required ? f.label : f.label.includes("opcional") ? f.label : `${f.label} (opcional)`;
      if (f.multiline) {
        return (
          <label key={f.name} className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{label}</span>
            <textarea
              aria-label={label}
              autoComplete="off"
              spellCheck={false}
              className={cn(inputBaseClass, "h-28 py-2 font-mono text-xs", err ? "border-danger" : "border-border")}
              value={values[f.name] ?? ""}
              onChange={e => set(e.target.value)}
            />
            {err && <p className="text-xs text-danger">{err}</p>}
          </label>
        );
      }
      // Aviso, no bloqueo: la credencial se guarda igual; el motor sube la versión solo para la llamada a Responses.
      // El envoltorio es el mismo con y sin aviso: si cambiara, el campo se remontaría y perdería el foco al tipear.
      const stale = f.name === "api_version" && apiVersionBelowResponsesFloor(values[f.name]);
      return (
        <div key={f.name} className="flex flex-col gap-1.5">
          <Field
            label={label}
            type={f.secret ? "password" : "text"}
            autoComplete="off"
            value={values[f.name] ?? ""}
            onChange={e => set(e.target.value)}
            error={err}
          />
          {stale && (
            <p role="status" className="text-xs text-warning">
              Con una versión anterior a {AZURE_RESPONSES_MIN_API_VERSION}, las herramientas y el razonamiento
              (Claude Desktop/Code) pueden no funcionar en este destino. Se recomienda usar esa versión o una posterior.
            </p>
          )}
        </div>
      );
    })}
  </div>
);

export const ModalButtons: React.FC<{
  onCancel: () => void; onSubmit: () => void; submitLabel: string; busy?: boolean; cancelLabel?: string;
}> = ({ onCancel, onSubmit, submitLabel, busy, cancelLabel = "Cancelar" }) => (
  <>
    <Button variant="secondary" onClick={onCancel} disabled={busy}>{cancelLabel}</Button>
    <Button onClick={onSubmit} disabled={busy}>{busy ? "Guardando…" : submitLabel}</Button>
  </>
);
