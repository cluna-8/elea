// «Efectivos»: qué puede usar de verdad una persona, grupo o llave, de dónde sale el techo y qué
// perfiles aplican con su origen; más un probador «¿puede usar este modelo?».
import React, { useEffect, useState } from "react";
import { Button, Card, StatusBadge } from "../../../../frontend/src/components/ui";
import { Notice, SelectField } from "../../redirect/ui";
import { SEMAFORO_LABELS, SEMAFORO_TONES } from "../../catalog/helpers";
import { accessApi, EffectiveAccess, EffectiveModel, PreviewResult } from "../accessApi";
import { motivoText, originLabel, riskLabel } from "./helpers";
import type { AccessCtx } from "./types";

type Kind = "user" | "group" | "key";
const KINDS: { value: Kind; label: string }[] = [
  { value: "user", label: "Usuario" },
  { value: "group", label: "Grupo" },
  { value: "key", label: "Conexión" },
];

const estado = (s: EffectiveModel["semaforo"]) => (typeof s === "string" ? s : s?.estado ?? "unclassified");

export const EffectivePanel: React.FC<{ ctx: AccessCtx }> = ({ ctx }) => {
  const [kind, setKind] = useState<Kind>("user");
  const [subject, setSubject] = useState("");
  const [data, setData] = useState<EffectiveAccess | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [testing, setTesting] = useState(false);
  const options = kind === "group" ? ctx.lookups.groups.map(g => ({ value: g.id, label: g.name }))
    : kind === "user" ? ctx.lookups.users.map(u => ({ value: u.id, label: u.username }))
      : ctx.lookups.keys.map(k => ({ value: k.id, label: k.name }));

  useEffect(() => {
    setData(null);
    setResult(null);
    setError(null);
    if (!subject) return;
    let live = true;
    setLoading(true);
    accessApi.effective({ [kind]: subject })
      .then(d => { if (live) setData(d); })
      .catch(e => { if (live) setError((e as Error).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [kind, subject]);

  const test = async () => {
    setTesting(true);
    setError(null);
    try {
      setResult(await accessApi.preview({ [kind]: subject, model }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SelectField label="Ver acceso de" value={kind} onChange={v => { setKind(v as Kind); setSubject(""); }} options={KINDS} />
        <SelectField label={KINDS.find(k => k.value === kind)!.label} value={subject} onChange={setSubject} options={options}
          placeholder={options.length ? "Elegí…" : "No hay elementos para elegir"} />
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {!subject ? (
        <p className="text-sm text-text-tertiary">Elegí una persona, un grupo o una conexión para ver qué modelos puede usar.</p>
      ) : loading ? (
        <p role="status" className="text-sm text-text-tertiary">Calculando acceso…</p>
      ) : data && (
        <>
          <Notice tone="info">
            {data.restringe
              ? `Puede usar ${data.permitidos.length === 1 ? "1 modelo" : `${data.permitidos.length} modelos`}: sus perfiles y el techo recortan el catálogo.`
              : "No tiene restricciones por perfil: puede usar todos los modelos habilitados."}
          </Notice>
          <div className="grid gap-4 md:grid-cols-2">
            <Card title="Techo aplicado">
              {data.techo ? (
                <p className="text-sm text-text-primary">
                  {riskLabel(data.techo.risk_level)} · viene de: {originLabel(data.techo.origen)} ·{" "}
                  {data.techo.count === 1 ? "1 modelo" : `${data.techo.count} modelos`}
                </p>
              ) : <p className="text-sm text-text-secondary">Sin techo.</p>}
            </Card>
            <Card title="Perfiles aplicados">
              {data.perfiles.length === 0 ? (
                <p className="text-sm text-text-secondary">Ningún perfil asignado.</p>
              ) : (
                <ul aria-label="Perfiles aplicados" className="space-y-1 text-sm">
                  {data.perfiles.map(p => (
                    <li key={p.id} className="flex items-center gap-2">
                      <span className="font-semibold text-text-primary">{p.name}</span>
                      <StatusBadge tone="neutral">{originLabel(p.origen)}</StatusBadge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          <Card title="Modelos que puede usar" noPadding>
            {data.permitidos.length === 0 ? (
              <p className="px-5 py-6 text-sm text-text-secondary">No puede usar ningún modelo.</p>
            ) : (
              <div className="w-full overflow-x-auto">
                <table className="w-full text-xs">
                  <caption className="sr-only">Modelos permitidos</caption>
                  <thead>
                    <tr className="border-b border-border text-left text-text-secondary">
                      <th scope="col" className="px-4 py-2 font-medium">Modelo</th>
                      <th scope="col" className="px-4 py-2 font-medium">Proveedor</th>
                      <th scope="col" className="px-4 py-2 font-medium">Semáforo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.permitidos.map(m => (
                      <tr key={m.id} className="border-b border-border">
                        <td className="px-4 py-2">
                          <span className="font-semibold text-text-primary">{m.name}</span>
                          <span className="block font-mono text-text-tertiary">{m.public_id}</span>
                        </td>
                        <td className="px-4 py-2">{m.provider}</td>
                        <td className="px-4 py-2">
                          <StatusBadge tone={SEMAFORO_TONES[estado(m.semaforo) as keyof typeof SEMAFORO_TONES] ?? "neutral"}>
                            {SEMAFORO_LABELS[estado(m.semaforo) as keyof typeof SEMAFORO_LABELS] ?? estado(m.semaforo)}
                          </StatusBadge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Card title="¿Puede usar este modelo?">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[14rem] flex-1">
                <SelectField label="Modelo a probar" value={model} onChange={v => { setModel(v); setResult(null); }}
                  options={ctx.entries.map(e => ({ value: e.public_id, label: e.name }))} placeholder="Elegí un modelo…" />
              </div>
              <Button onClick={() => void test()} disabled={!model || testing}>{testing ? "Probando…" : "Probar"}</Button>
            </div>
            {result && (
              <div role="status" className="mt-3 text-sm">
                <StatusBadge tone={result.allowed ? "ok" : "danger"}>
                  {result.allowed ? "Puede usar este modelo" : "No puede usar este modelo"}
                </StatusBadge>
                {!result.allowed && result.motivo && <p className="mt-1 text-text-secondary">{motivoText(result.motivo)}</p>}
                {result.allowed && result.permitidos_origen && (
                  <p className="mt-1 text-text-secondary">Lo permite: {originLabel(result.permitidos_origen)}.</p>
                )}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
};
