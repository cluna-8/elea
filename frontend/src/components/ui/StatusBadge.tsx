import React from "react";
import { cn } from "./cn";

export type BadgeTone = "ok" | "warn" | "danger" | "info" | "neutral";

export interface StatusBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  /** Semántica de la pill: éxito, advertencia, peligro, info o neutro. */
  tone: BadgeTone;
  /** Muestra un punto de color a la izquierda del texto. */
  dot?: boolean;
  className?: string;
  children?: React.ReactNode;
}

// Fondo tenue + texto oscuro (tokens semánticos), distinto del acento.
const TONE: Record<BadgeTone, string> = {
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  danger: "bg-danger-bg text-danger",
  info: "bg-info-bg text-info",
  neutral: "bg-surface-2 text-text-secondary",
};

const DOT: Record<BadgeTone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
  neutral: "bg-text-tertiary",
};

/**
 * Pill de estado semántica. Uso: <StatusBadge tone="ok">Activo</StatusBadge>
 */
export const StatusBadge: React.FC<StatusBadgeProps> = ({
  tone,
  dot,
  className,
  children,
  ...rest
}) => {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE[tone],
        className
      )}
      {...rest}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", DOT[tone])} />}
      {children}
    </span>
  );
};
