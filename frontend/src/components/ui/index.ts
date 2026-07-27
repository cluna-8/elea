// Kit de componentes 029 (tema claro Foundry) — FR-007.
// Las páginas importan de acá: import { Card, Button, StatusBadge } from "../components/ui";
// Todos consumen tokens (index.css / tailwind.config) — nada de hex hardcodeado.
export { cn } from "./cn";
export { Card } from "./Card";
export type { CardProps } from "./Card";
export { PageHeader } from "./PageHeader";
export type { PageHeaderProps } from "./PageHeader";
export { StatusBadge } from "./StatusBadge";
export type { StatusBadgeProps, BadgeTone } from "./StatusBadge";
export { Button } from "./Button";
export type { ButtonProps, ButtonVariant, ButtonSize } from "./Button";
export {
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
} from "./Table";
export type { TableProps, TableColumn } from "./Table";
export { Field, inputBaseClass } from "./Field";
export type { FieldProps } from "./Field";
export { Toggle } from "./Toggle";
export type { ToggleProps } from "./Toggle";
