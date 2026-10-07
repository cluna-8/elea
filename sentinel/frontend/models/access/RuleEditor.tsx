// Editor de reglas de un perfil: efecto, selector y valor (sugerido según el selector).
import React from "react";
import { Button, cn, inputBaseClass } from "../../../../frontend/src/components/ui";
import type { ProfileRule, RuleEffect, RuleSelector } from "../accessApi";
import { EFFECT_LABELS, SELECTORS, SELECTOR_LABELS, VALUE_LABELS, hasInclude } from "./helpers";

const selectClass = cn(inputBaseClass, "border-border");

interface Props {
  rules: ProfileRule[];
  onChange: (rules: ProfileRule[]) => void;
  entries: { id: string; name: string }[];
}

export const RuleEditor: React.FC<Props> = ({ rules, onChange, entries }) => {
  const set = (i: number, patch: Partial<ProfileRule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const firstValue = (s: RuleSelector) => Object.keys(VALUE_LABELS[s] ?? {})[0] ?? "";
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Reglas</span>
      {rules.length === 0 && (
        <p className="text-xs text-text-tertiary">Todavía no hay reglas: el perfil no permite ningún modelo.</p>
      )}
      {rules.map((r, i) => {
        const n = i + 1;
        const suggested = VALUE_LABELS[r.selector];
        return (
          <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-[8rem_10rem_1fr_auto]">
            <select aria-label={`Efecto de la regla ${n}`} className={selectClass} value={r.effect}
              onChange={e => set(i, { effect: e.target.value as RuleEffect })}>
              {(Object.keys(EFFECT_LABELS) as RuleEffect[]).map(k => <option key={k} value={k}>{EFFECT_LABELS[k]}</option>)}
            </select>
            <select aria-label={`Selector de la regla ${n}`} className={selectClass} value={r.selector}
              onChange={e => set(i, { selector: e.target.value as RuleSelector, value: firstValue(e.target.value as RuleSelector) })}>
              {SELECTORS.map(s => <option key={s} value={s}>{SELECTOR_LABELS[s][0].toUpperCase() + SELECTOR_LABELS[s].slice(1)}</option>)}
            </select>
            {suggested ? (
              <select aria-label={`Valor de la regla ${n}`} className={selectClass} value={r.value}
                onChange={e => set(i, { value: e.target.value })}>
                {!(r.value in suggested) && <option value={r.value}>{r.value || "Elegí…"}</option>}
                {Object.entries(suggested).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            ) : r.selector === "entrada" ? (
              <select aria-label={`Valor de la regla ${n}`} className={selectClass} value={r.value}
                onChange={e => set(i, { value: e.target.value })}>
                <option value="">Elegí un modelo…</option>
                {r.value && !entries.some(e => e.id === r.value) && <option value={r.value}>{r.value}</option>}
                {entries.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            ) : (
              <input aria-label={`Valor de la regla ${n}`} className={selectClass} value={r.value}
                placeholder={r.selector === "jurisdiccion" ? "Ej.: EU" : "Ej.: mistral"}
                onChange={e => set(i, { value: e.target.value })} />
            )}
            <Button variant="ghost" aria-label={`Quitar la regla ${n}`} onClick={() => onChange(rules.filter((_, j) => j !== i))}>Quitar</Button>
          </div>
        );
      })}
      <div>
        <Button variant="secondary" onClick={() => onChange([...rules, { effect: "include", selector: "semaforo", value: "eu_ok" }])}>
          Agregar regla
        </Button>
      </div>
      {rules.length > 0 && !hasInclude(rules) && (
        <p className="text-xs text-warn">Sin ninguna regla que incluya, el perfil no permite ningún modelo.</p>
      )}
    </div>
  );
};
