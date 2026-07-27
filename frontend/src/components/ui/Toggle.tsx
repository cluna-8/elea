import React from "react";
import { cn } from "./cn";

export interface ToggleProps {
  /** Estado on/off (controlado). */
  checked: boolean;
  /** Se dispara con el nuevo valor — la página persiste al instante (FR-008). */
  onChange: (checked: boolean) => void;
  /** Etiqueta accesible (usar cuando no hay texto visible asociado). */
  label?: string;
  disabled?: boolean;
  size?: "sm" | "md";
  className?: string;
  id?: string;
}

/**
 * Switch accesible (role=switch, aria-checked, teclado). Consume el acento.
 * Uso: <Toggle checked={on} onChange={setOn} label="Headroom automático" />
 */
export const Toggle: React.FC<ToggleProps> = ({
  checked,
  onChange,
  label,
  disabled,
  size = "md",
  className,
  id,
}) => {
  const dims =
    size === "sm"
      ? { track: "h-5 w-9", knob: "h-4 w-4", on: "translate-x-4" }
      : { track: "h-6 w-11", knob: "h-5 w-5", on: "translate-x-5" };

  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={cn(
        "relative inline-flex shrink-0 items-center rounded-full transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        "disabled:opacity-50 disabled:pointer-events-none",
        dims.track,
        checked ? "bg-primary" : "bg-border-strong",
        className
      )}
    >
      <span
        className={cn(
          "inline-block transform rounded-full bg-white shadow-sm transition-transform",
          dims.knob,
          "translate-x-0.5",
          checked && dims.on
        )}
      />
    </button>
  );
};
