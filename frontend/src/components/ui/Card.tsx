import React from "react";
import { cn } from "./cn";

export interface CardProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** Título opcional (h3). Si se pasa, se renderiza un header con divisor. */
  title?: React.ReactNode;
  /** Acciones alineadas a la derecha del header (botones, links). */
  actions?: React.ReactNode;
  /** Quita el padding interno del cuerpo (para tablas edge-to-edge). */
  noPadding?: boolean;
  className?: string;
  children?: React.ReactNode;
}

/**
 * Superficie blanca con borde fino, radio 8 y sombra suave (tokens 029).
 * Uso: <Card title="Estado" actions={<Button.../>}>...</Card>
 */
export const Card: React.FC<CardProps> = ({
  title,
  actions,
  noPadding,
  className,
  children,
  ...rest
}) => {
  return (
    <div
      className={cn(
        "bg-surface border border-border rounded-card shadow-card",
        className
      )}
      {...rest}
    >
      {(title || actions) && (
        <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border">
          {title ? (
            <h3 className="text-[15px] font-semibold text-text-primary">{title}</h3>
          ) : (
            <span />
          )}
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={cn(!noPadding && "p-5")}>{children}</div>
    </div>
  );
};
