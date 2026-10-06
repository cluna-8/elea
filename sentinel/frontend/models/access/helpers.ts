// Textos y reglas puras de la pestaña «Acceso»: reglas legibles, etiquetas de valores sugeridos, niveles
// de riesgo del AI Act y qué puede escribir cada rol (solo decide botones: el backend aplica igual).
import type { Profile, ProfileKind, ProfileRule, RiskLevel, RuleEffect, RuleSelector } from "../accessApi";

export const SELECTORS: RuleSelector[] = ["semaforo", "jurisdiccion", "proveedor", "capacidad", "entrada"];
export const SELECTOR_LABELS: Record<RuleSelector, string> = {
  semaforo: "semáforo",
  jurisdiccion: "jurisdicción",
  proveedor: "proveedor",
  capacidad: "capacidad",
  entrada: "modelo",
};
export const EFFECT_LABELS: Record<RuleEffect, string> = { include: "Incluye", exclude: "Excluye" };
export const KIND_LABELS: Record<ProfileKind, string> = {
  company: "Perfil de empresa",
  ceiling: "Techo de riesgo",
  key: "Perfil de llave",
};

/** Valores sugeridos por selector (los demás se escriben o se eligen del catálogo). */
export const VALUE_LABELS: Partial<Record<RuleSelector, Record<string, string>>> = {
  semaforo: { eu_ok: "admisible UE", standard: "estándar", unclassified: "sin clasificar" },
  capacidad: { small: "pequeña", standard: "estándar", frontier: "de frontera" },
};

export const RISK_LEVELS: { id: RiskLevel; label: string; hint: string }[] = [
  { id: "minimal", label: "Mínimo", hint: "Sin obligaciones específicas del AI Act." },
  { id: "limited", label: "Limitado", hint: "Obligaciones de transparencia." },
  { id: "high_risk_annex1", label: "Alto riesgo (Anexo I)", hint: "Productos regulados por legislación sectorial de la UE." },
  { id: "high_risk_annex3", label: "Alto riesgo (Anexo III)", hint: "Usos sensibles: empleo, crédito, educación, etc." },
];

export const ORIGEN_LABELS: Record<string, string> = {
  user: "Usuario", group: "Grupo", tenant: "Organización", key: "Llave",
};
export const originLabel = (o: string | null | undefined) => (o ? ORIGEN_LABELS[o] ?? o : "—");
export const riskLabel = (level: string) => RISK_LEVELS.find(r => r.id === level)?.label ?? level;

export function valueLabel(selector: RuleSelector, value: string, entryName?: (id: string) => string | undefined): string {
  if (selector === "entrada") return entryName?.(value) ?? value;
  return VALUE_LABELS[selector]?.[value] ?? value;
}

/** «Incluye: semáforo = admisible UE». */
export function describeRule(r: ProfileRule, entryName?: (id: string) => string | undefined): string {
  return `${EFFECT_LABELS[r.effect]}: ${SELECTOR_LABELS[r.selector] ?? r.selector} = ${valueLabel(r.selector, r.value, entryName)}`;
}

export const allowsLabel = (n: number) => (n === 1 ? "permite 1 modelo" : `permite ${n} modelos`);

export interface AccessPerms {
  /** Escribe perfiles `company`/`key` y asignaciones. */
  canAdmin: boolean;
  /** Escribe techos por riesgo y perfiles `ceiling`. */
  canCeiling: boolean;
}
const ADMIN_ROLES = ["admin", "tenant_admin", "super_admin"];
export function accessPermsFor(role: string): AccessPerms {
  return { canAdmin: ADMIN_ROLES.includes(role), canCeiling: role === "compliance_officer" };
}
export const canWriteKind = (p: AccessPerms, kind: ProfileKind) => (kind === "ceiling" ? p.canCeiling : p.canAdmin);

export const profileName = (profiles: Pick<Profile, "id" | "name">[], id: string) =>
  profiles.find(p => p.id === id)?.name ?? "Perfil dado de baja";

export const hasInclude = (rules: ProfileRule[]) => rules.some(r => r.effect === "include");

export function validateRules(rules: ProfileRule[]): string | null {
  return rules.some(r => !r.value.trim()) ? "Completá el valor de cada regla." : null;
}

const MOTIVOS: Record<string, string> = {
  profile_not_allowed: "Ningún perfil asignado permite este modelo.",
  above_ceiling: "El techo de riesgo de la organización no lo permite.",
  key_profile: "El perfil de la llave no lo permite.",
};
export const motivoText = (m: string | null | undefined) => (m ? MOTIVOS[m] ?? m : "");
