import React from "react";
import { cn } from "./cn";

export interface PageHeaderProps {
  /** Título de la página (h1, 24/600). */
  title: React.ReactNode;
  /** Subtítulo/descriptor opcional bajo el título. */
  subtitle?: React.ReactNode;
  /** Acciones a la derecha (botones primarios/secundarios). */
  actions?: React.ReactNode;
  className?: string;
}

/**
 * Encabezado de página: h1 + subtítulo + zona de acciones a la derecha.
 * Uso: <PageHeader title="Usuarios" subtitle="..." actions={<Button/>} />
 */
export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  actions,
  className,
}) => {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between mb-6",
        className
      )}
    >
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold text-text-primary leading-tight truncate">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm text-text-secondary">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 shrink-0">{actions}</div>
      )}
    </div>
  );
};
