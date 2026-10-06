// Piezas compartidas de la pantalla: selector, selector de alcance, aviso y diálogo de motivo.
// Todo sobre el kit de la consola (tokens 029), sin estilos propios.
import React, { useId, useState } from "react";
import { Button, Field, inputBaseClass, cn } from "../../../frontend/src/components/ui";
import { SCOPE_TYPES, SCOPE_TYPE_LABELS, ScopeType } from "./catalog";
import type { Lookups } from "./helpers";

export const SelectField: React.FC<{
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  error?: string;
  hint?: string;
  disabled?: boolean;
  placeholder?: string;
}> = ({ label, value, onChange, options, error, hint, disabled, placeholder }) => {
  const id = useId();
  return (
    <Field label={<span id={`${id}-l`}>{label}</span>} error={error} hint={hint}>
      <select
        aria-labelledby={`${id}-l`}
        className={cn(inputBaseClass, error ? "border-danger" : "border-border")}
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  );
};

/** Alcance: tipo + a quién (por nombre; se envía el id). */
export const ScopePicker: React.FC<{
  type: ScopeType;
  value: string;
  lookups: Lookups;
  onChange: (type: ScopeType, value: string) => void;
  error?: string;
}> = ({ type, value, lookups, onChange, error }) => {
  const options =
    type === "group" ? lookups.groups.map(g => ({ value: g.id, label: g.name }))
    : type === "user" ? lookups.users.map(u => ({ value: u.id, label: u.username }))
    : type === "connection" ? lookups.keys.map(k => ({ value: k.id, label: k.name }))
    : [];
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <SelectField
        label="Aplica a"
        value={type}
        onChange={v => onChange(v as ScopeType, "")}
        options={SCOPE_TYPES.map(t => ({ value: t, label: SCOPE_TYPE_LABELS[t] }))}
      />
      {type !== "tenant" && (
        <SelectField
          label={SCOPE_TYPE_LABELS[type]}
          value={value}
          onChange={v => onChange(type, v)}
          options={options}
          placeholder={options.length ? "Elegí…" : "No hay elementos para elegir"}
          error={error}
        />
      )}
    </div>
  );
};

export const Notice: React.FC<{ tone: "error" | "ok" | "info"; children: React.ReactNode; onClose?: () => void }> = ({ tone, children, onClose }) => (
  <div
    role={tone === "error" ? "alert" : "status"}
    className={cn(
      "flex items-start justify-between gap-3 rounded-md px-4 py-3 text-sm mb-4",
      tone === "error" && "bg-danger-bg text-danger",
      tone === "ok" && "bg-ok-bg text-ok",
      tone === "info" && "bg-info-bg text-info",
    )}
  >
    <div>{children}</div>
    {onClose && (
      <button type="button" className="text-xs underline shrink-0" onClick={onClose}>Cerrar</button>
    )}
  </div>
);

/** Diálogo de confirmación con motivo obligatorio (revocar, habilitar, borrar postura…). */
export const ReasonDialog: React.FC<{
  title: string;
  description?: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  extra?: React.ReactNode;
  onConfirm: (reason: string) => Promise<void> | void;
  onCancel: () => void;
  reasonOptional?: boolean;
  /** Confirmación simple: la API no registra motivo para esta acción. */
  noReason?: boolean;
}> = ({ title, description, confirmLabel, danger, extra, onConfirm, onCancel, reasonOptional, noReason }) => {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ok = noReason || reasonOptional || reason.trim().length >= 3;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-lg rounded-card bg-surface p-5 shadow-card border border-border">
        <h3 className="text-[15px] font-semibold text-text-primary mb-2">{title}</h3>
        {description && <div className="text-sm text-text-secondary mb-3">{description}</div>}
        {extra}
        {!noReason && <label className="flex flex-col gap-1.5 mt-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
            Motivo{reasonOptional ? " (opcional)" : ""}
          </span>
          <textarea
            className={cn(inputBaseClass, "h-20 py-2 border-border")}
            value={reason}
            onChange={e => setReason(e.target.value)}
          />
        </label>}
        {error && <p className="text-xs text-danger mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>Cancelar</Button>
          <Button
            variant={danger ? "danger" : "primary"}
            disabled={!ok || busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm(reason.trim());
              } catch (e) {
                setError(e instanceof Error ? e.message : "No se pudo completar la acción.");
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
};

export const EmptyRow: React.FC<{ cols: number; children: React.ReactNode }> = ({ cols, children }) => (
  <tr><td colSpan={cols} className="px-4 py-6 text-center text-sm text-text-tertiary">{children}</td></tr>
);

export const tableClass = "w-full text-sm text-left";
export const thClass = "px-4 py-2 text-xs font-semibold uppercase tracking-wide text-text-secondary bg-surface-2";
export const tdClass = "px-4 py-2 border-t border-border align-top";
