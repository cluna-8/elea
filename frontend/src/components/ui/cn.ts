import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// Une clases condicionales (clsx) y resuelve conflictos de tailwind (twMerge)
// para que un `className` que pasa la página gane sobre el default del kit.
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
