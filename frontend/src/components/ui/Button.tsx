import React from "react";
import { cn } from "./cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Icono opcional a la izquierda del texto. */
  leftIcon?: React.ReactNode;
  className?: string;
}

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium " +
  "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-canvas " +
  "disabled:opacity-50 disabled:pointer-events-none";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-white hover:bg-primary-hover",
  secondary:
    "bg-surface text-text-primary border border-border hover:bg-surface-2",
  ghost: "bg-transparent text-text-secondary hover:bg-surface-2 hover:text-text-primary",
  danger: "bg-danger text-white hover:opacity-90",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
  lg: "h-11 px-5 text-sm",
};

/**
 * Botón con variantes primary/secondary/ghost/danger. Consume tokens de acento.
 * Uso: <Button variant="primary" onClick={...}>Guardar</Button>
 */
export const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  size = "md",
  leftIcon,
  className,
  children,
  type = "button",
  ...rest
}) => {
  return (
    <button
      type={type}
      className={cn(BASE, VARIANT[variant], SIZE[size], className)}
      {...rest}
    >
      {leftIcon && <span className="shrink-0">{leftIcon}</span>}
      {children}
    </button>
  );
};
