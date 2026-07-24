import React, { useId } from "react";
import { cn } from "./cn";

export interface FieldProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Etiqueta (12/600 uppercase, --text-secondary). */
  label?: React.ReactNode;
  /** Texto de ayuda bajo el input. */
  hint?: React.ReactNode;
  /** Mensaje de error (tiñe el borde y el texto en danger). */
  error?: React.ReactNode;
  /** Contenido custom en lugar de <input> (ej. un <select>). */
  children?: React.ReactNode;
  className?: string;
  /** className del <input>. */
  inputClassName?: string;
}

export const inputBaseClass =
  "w-full h-9 rounded-md border bg-surface px-3 text-sm text-text-primary " +
  "placeholder:text-text-tertiary transition-colors " +
  "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-canvas";

/**
 * Campo de formulario: label + input + hint/error. Consume tokens.
 * Uso: <Field label="Usuario" value={v} onChange={...} error={err} />
 */
export const Field: React.FC<FieldProps> = ({
  label,
  hint,
  error,
  children,
  className,
  inputClassName,
  id,
  ...rest
}) => {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <label
          htmlFor={fieldId}
          className="text-xs font-semibold uppercase tracking-wide text-text-secondary"
        >
          {label}
        </label>
      )}
      {children ?? (
        <input
          id={fieldId}
          className={cn(
            inputBaseClass,
            error ? "border-danger" : "border-border",
            inputClassName
          )}
          aria-invalid={!!error}
          {...rest}
        />
      )}
      {error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : (
        hint && <p className="text-xs text-text-tertiary">{hint}</p>
      )}
    </div>
  );
};
