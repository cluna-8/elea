import React from "react";
import { cn } from "./cn";

/* ---------------------------------------------------------------------------
 * Table — dos formas de uso:
 *  1) Declarativa:  <Table columns={[...]} rows={[...]} />
 *  2) Composición:  <Table><THead>...<TBody>...</Table>  (con THead/TBody/TR/TH/TD)
 * Header en --surface-2 (sticky), filas con borde inferior, contenedor con
 * overflow-x:auto (el body nunca hace scroll lateral).
 * ------------------------------------------------------------------------- */

export interface TableColumn<Row> {
  /** Clave única / accesor si no se pasa `render`. */
  key: string;
  header: React.ReactNode;
  /** Render custom de la celda; si falta, usa row[key]. */
  render?: (row: Row, index: number) => React.ReactNode;
  className?: string;
  /** Alineación del contenido. */
  align?: "left" | "center" | "right";
}

export interface TableProps<Row = Record<string, unknown>>
  extends Omit<React.HTMLAttributes<HTMLTableElement>, "children"> {
  columns?: TableColumn<Row>[];
  rows?: Row[];
  /** Clave estable por fila (índice por defecto). */
  rowKey?: (row: Row, index: number) => string | number;
  /** Mensaje cuando `rows` está vacío. */
  emptyLabel?: React.ReactNode;
  className?: string;
  /** className del contenedor con overflow-x. */
  wrapperClassName?: string;
  children?: React.ReactNode;
}

const ALIGN = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
} as const;

function TableRoot<Row extends Record<string, unknown>>({
  columns,
  rows,
  rowKey,
  emptyLabel = "Sin datos",
  className,
  wrapperClassName,
  children,
  ...rest
}: TableProps<Row>) {
  const declarative = !!columns;
  return (
    <div
      className={cn(
        "w-full overflow-x-auto rounded-card border border-border",
        wrapperClassName
      )}
    >
      <table
        className={cn("w-full border-collapse text-sm", className)}
        {...rest}
      >
        {declarative ? (
          <>
            <THead>
              <TR>
                {columns!.map((c) => (
                  <TH key={c.key} className={cn(ALIGN[c.align ?? "left"], c.className)}>
                    {c.header}
                  </TH>
                ))}
              </TR>
            </THead>
            <TBody>
              {(rows ?? []).length === 0 ? (
                <TR>
                  <TD
                    colSpan={columns!.length}
                    className="text-center text-text-tertiary py-8"
                  >
                    {emptyLabel}
                  </TD>
                </TR>
              ) : (
                (rows ?? []).map((row, i) => (
                  <TR key={rowKey ? rowKey(row, i) : i}>
                    {columns!.map((c) => (
                      <TD key={c.key} className={cn(ALIGN[c.align ?? "left"], c.className)}>
                        {c.render ? c.render(row, i) : (row[c.key] as React.ReactNode)}
                      </TD>
                    ))}
                  </TR>
                ))
              )}
            </TBody>
          </>
        ) : (
          children
        )}
      </table>
    </div>
  );
}

export const THead: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = ({
  className,
  ...rest
}) => (
  <thead
    className={cn("bg-surface-2 sticky top-0 z-10", className)}
    {...rest}
  />
);

export const TBody: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = (
  props
) => <tbody {...props} />;

export const TR: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = ({
  className,
  ...rest
}) => (
  <tr
    className={cn("border-b border-border last:border-0", className)}
    {...rest}
  />
);

export const TH: React.FC<React.ThHTMLAttributes<HTMLTableCellElement>> = ({
  className,
  ...rest
}) => (
  <th
    className={cn(
      "px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-text-secondary",
      className
    )}
    {...rest}
  />
);

export const TD: React.FC<React.TdHTMLAttributes<HTMLTableCellElement>> = ({
  className,
  ...rest
}) => (
  <td
    className={cn("px-4 py-3 align-middle text-text-primary", className)}
    {...rest}
  />
);

// Compound: <Table.Head>, <Table.Body>, etc. además de los named exports.
export const Table = Object.assign(TableRoot, {
  Head: THead,
  Body: TBody,
  Row: TR,
  HeaderCell: TH,
  Cell: TD,
});
