// Pestaña «Habilitación» (057 FR-029): reglas por datos que hacen que un modelo nazca bloqueado hasta que
// administración o cumplimiento lo habilite con motivo. El panel no sabe de ningún proveedor «bloqueado»: muestra
// las reglas que hay. Sin reglas (el valor de Eleia) ningún modelo nace bloqueado.
import React, { useCallback, useEffect, useState } from "react";
import { Button, Card, StatusBadge, inputBaseClass, cn } from "../../../frontend/src/components/ui";
import { Notice, ReasonDialog, EmptyRow, tableClass, tdClass, thClass } from "../redirect/ui";
import { catalogApi } from "./api";
import {
  canAddRule, canDeleteRule, EnablementRule, levelLabel, Permissions, RULE_KINDS, RULE_KIND_HINTS, RULE_KIND_LABELS,
  RuleKind,
} from "./helpers";
import { SelectField } from "../redirect/ui";

export const EnablementTab: React.FC<{ perms: Permissions; reload: () => Promise<void> }> = ({ perms, reload }) => {
  const [rules, setRules] = useState<EnablementRule[] | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<EnablementRule | null>(null);
  const [kind, setKind] = useState<RuleKind>("provider");
  const [value, setValue] = useState("");
  const [level, setLevel] = useState<"tenant" | "installation">("tenant");

  const load = useCallback(async () => {
    try {
      setRules(await catalogApi.enablementRules());
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
      setRules([]);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const openAdd = () => { setKind("provider"); setValue(""); setLevel("tenant"); setAdding(true); };
  const changedText = (n: number, verb: string) =>
    n > 0 ? `${n} modelo(s) pasaron a ${verb}.` : "Ningún modelo cambió de estado.";

  return (
    <div>
      {msg && <Notice tone={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      <p className="text-sm text-text-secondary mb-4">
        Una regla hace que un modelo nazca <strong>bloqueado por defecto</strong> (por proveedor, por host de la API o por
        jurisdicción de su ficha) hasta que administración o cumplimiento lo habilite con un motivo. Habilitar no relaja la residencia.
      </p>
      {canAddRule(perms) && (
        <div className="flex justify-end mb-3"><Button onClick={openAdd}>Agregar regla</Button></div>
      )}
      <Card noPadding title="Reglas de habilitación">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Tipo</th><th className={thClass}>Valor</th><th className={thClass}>Alcance</th>
              <th className={thClass}>Motivo</th><th className={thClass}>Acciones</th>
            </tr></thead>
            <tbody>
              {rules === null && <EmptyRow cols={5}>Cargando…</EmptyRow>}
              {rules?.length === 0 && (
                <EmptyRow cols={5}>No hay reglas de habilitación: ningún modelo nace bloqueado por defecto.</EmptyRow>
              )}
              {rules?.map(r => (
                <tr key={r.id}>
                  <td className={tdClass}>{RULE_KIND_LABELS[r.kind] ?? r.kind}</td>
                  <td className={cn(tdClass, "font-mono text-xs")}>{r.value}</td>
                  <td className={tdClass}>
                    <StatusBadge tone={r.level === "installation" ? "info" : "neutral"}>{levelLabel(r.level)}</StatusBadge>
                  </td>
                  <td className={tdClass}>{r.reason}</td>
                  <td className={tdClass}>
                    {canDeleteRule(perms, r) && (
                      <Button size="sm" variant="danger" aria-label={`Quitar regla ${r.kind} ${r.value}`}
                        onClick={() => setRemoving(r)}>Quitar</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {adding && (
        <ReasonDialog
          title="Agregar regla de habilitación"
          description="Los modelos que coincidan quedan bloqueados hasta que se los habilite con motivo."
          confirmLabel="Guardar regla"
          extra={
            <div className="grid grid-cols-1 gap-3">
              <SelectField label="Tipo de regla" value={kind} onChange={v => setKind(v as RuleKind)}
                options={RULE_KINDS.map(k => ({ value: k, label: RULE_KIND_LABELS[k] }))} hint={RULE_KIND_HINTS[kind]} />
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Valor</span>
                <input className={cn(inputBaseClass, "border-border")} value={value} onChange={e => setValue(e.target.value)} />
              </label>
              {perms.operator && (
                <SelectField label="Nivel" value={level} onChange={v => setLevel(v as "tenant" | "installation")}
                  options={[{ value: "tenant", label: "Organización" }, { value: "installation", label: "Instalación" }]} />
              )}
            </div>
          }
          onCancel={() => setAdding(false)}
          onConfirm={async reason => {
            if (!value.trim()) throw new Error("Falta el valor de la regla.");
            const r = await catalogApi.createEnablementRule({ kind, value: value.trim(), level, reason });
            setAdding(false);
            setMsg({ tone: "ok", text: `Regla agregada. ${changedText(r.changed ?? 0, "bloqueados")}` });
            await load();
            await reload();
          }}
        />
      )}
      {removing && (
        <ReasonDialog
          title={`Quitar la regla ${RULE_KIND_LABELS[removing.kind]} «${removing.value}»`}
          description="Los modelos que solo esta regla bloqueaba dejan de estar bloqueados."
          confirmLabel="Quitar" danger noReason
          onCancel={() => setRemoving(null)}
          onConfirm={async () => {
            const r = await catalogApi.deleteEnablementRule(removing.id);
            setRemoving(null);
            setMsg({ tone: "ok", text: `Regla quitada. ${changedText(r.changed ?? 0, "desbloqueados")}` });
            await load();
            await reload();
          }}
        />
      )}
    </div>
  );
};
