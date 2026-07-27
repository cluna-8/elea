import React, { useState } from "react";
import { Field, inputBaseClass } from "./Field";
import { cn } from "./cn";

export interface PasswordFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (valor: string) => void;
  error?: string | null;
  hint?: React.ReactNode;
  /** `new-password` (default) para credenciales que se están definiendo; `current-password`
   *  para la que ya se tiene. Es lo que decide si el navegador ofrece o guarda. */
  autoComplete?: "new-password" | "current-password";
  placeholder?: string;
}

/** Campo de contraseña con opción de verla.
 *
 *  Vive en el kit y no en una página porque lo usan dos pantallas distintas (el alta y el
 *  reseteo de Usuarios, y el cambio de la propia contraseña desde la sesión): dos copias es
 *  la garantía de que una se quede sin el "Mostrar" o sin el `autoComplete` correcto.
 *
 *  El "Mostrar" existe porque en el alta y el reseteo el administrador escribe una credencial
 *  que después tiene que ENTREGARLE a otra persona: a ciegas, un tipeo se descubre recién
 *  cuando esa persona no puede entrar y hay que resetear de nuevo.
 *
 *  Sin `required`/`minLength` nativos a propósito: el navegador cortaría el submit con su
 *  propio globo, en el idioma del navegador y fuera del campo; el largo lo valida el
 *  formulario antes de enviar para poder decirlo en español y donde está el error. */
export const PasswordField: React.FC<PasswordFieldProps> = ({
  id,
  label,
  value,
  onChange,
  error,
  hint,
  autoComplete = "new-password",
  placeholder,
}) => {
  const [visible, setVisible] = useState(false);
  return (
    <Field id={id} label={label} error={error ?? undefined} hint={hint}>
      <div className="relative">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          aria-required
          aria-invalid={!!error}
          placeholder={placeholder}
          className={cn(inputBaseClass, error ? "border-danger" : "border-border", "pr-20")}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-pressed={visible}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1 text-[11px] font-semibold text-primary hover:text-primary-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {visible ? "Ocultar" : "Mostrar"}
        </button>
      </div>
    </Field>
  );
};
