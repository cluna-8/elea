// Pestaña «Vista previa»: qué destino se elegiría y por qué (misma función que el tráfico).
import React, { useState } from "react";
import { Button, Card, Field, StatusBadge } from "../../../frontend/src/components/ui";
import { FACES, FACE_LABELS, Face, POLICY_STATE_LABELS, POSTURE_MODE_LABELS, PolicyState, PostureMode, REQUEST_CLASSES, REQUEST_CLASS_LABELS } from "./catalog";
import { Destination, Lookups, PublishedModel } from "./helpers";
import { PreviewResult, redirectApi } from "./api";
import { Notice, SelectField } from "./ui";

// Motivos del resolver (`check_target` / `_substitution_reason`) en castellano.
export const SKIP_REASONS: Record<string, string> = {
  not_found: "no disponible para esta organización", not_offered: "sin oferta vigente",
  inactive: "inactivo", revoked: "revocado", blocked_by_default: "bloqueado por defecto",
  no_credential: "sin credencial o sin dirección base", residency: "fuera de la residencia permitida",
  foreign_entity: "entidad de otra jurisdicción no aceptada",
  offer_withdrawn: "oferta retirada", fallback_unavailable: "el principal no estaba disponible",
};

const UNAVAILABLE: Record<string, string> = {
  not_published: "El id no está publicado para este alcance.",
  no_rule: "Ninguna regla aplica a este pedido.",
  no_eligible_target: "Ningún destino de la regla es elegible.",
};

export function buildPreviewBody(f: { face: Face; public_id: string; request_class: string; connection_id: string; user_id: string; group_id: string }) {
  return {
    face: f.face,
    public_id: f.public_id.trim(),
    request_class: f.request_class || null,
    connection_id: f.connection_id || null,
    user_id: f.user_id || null,
    group_ids: f.group_id ? [f.group_id] : [],
  };
}

export const PreviewTab: React.FC<{ published: PublishedModel[]; destinations: Destination[]; lookups: Lookups }> = ({ published, destinations, lookups }) => {
  const [f, setF] = useState({ face: "openai_generic" as Face, public_id: "", request_class: "", connection_id: "", user_id: "", group_id: "" });
  const [res, setRes] = useState<PreviewResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const destName = (id: string) => destinations.find(d => d.id === id)?.name ?? "(destino)";
  const ids = Array.from(new Set(published.filter(p => p.face === f.face).map(p => p.public_id)));

  const run = async () => {
    if (!f.public_id.trim()) { setErr("Indicá el id que pediría la herramienta."); return; }
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await redirectApi.preview(buildPreviewBody(f))); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div>
      <Card title="Simular un pedido" className="mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <SelectField label="Cara" value={f.face} onChange={v => setF({ ...f, face: v as Face })}
            options={FACES.map(x => ({ value: x, label: FACE_LABELS[x] }))} />
          <Field label="Id pedido" value={f.public_id} list="rdx-preview-ids" onChange={e => setF({ ...f, public_id: e.target.value })} />
          <datalist id="rdx-preview-ids">{ids.map(i => <option key={i} value={i} />)}</datalist>
          <SelectField label="Clase de pedido" value={f.request_class} onChange={v => setF({ ...f, request_class: v })}
            options={REQUEST_CLASSES.map(c => ({ value: c, label: REQUEST_CLASS_LABELS[c] }))} placeholder="General" />
          <SelectField label="Conexión" value={f.connection_id} onChange={v => setF({ ...f, connection_id: v })}
            options={lookups.keys.map(k => ({ value: k.id, label: k.name }))} placeholder="Cualquiera" />
          <SelectField label="Usuario" value={f.user_id} onChange={v => setF({ ...f, user_id: v })}
            options={lookups.users.map(u => ({ value: u.id, label: u.username }))} placeholder="Cualquiera" />
          <SelectField label="Grupo" value={f.group_id} onChange={v => setF({ ...f, group_id: v })}
            options={lookups.groups.map(g => ({ value: g.id, label: g.name }))} placeholder="Ninguno" />
        </div>
        <div className="flex justify-end mt-4"><Button onClick={run} disabled={busy}>{busy ? "Calculando…" : "Ver resultado"}</Button></div>
      </Card>
      {err && <Notice tone="error">{err}</Notice>}
      {res && (
        <Card title="Resultado">
          <div className="flex flex-col gap-2 text-sm">
            <div>Estado de la política: <b>{POLICY_STATE_LABELS[res.state as PolicyState] ?? res.state}</b>
              {" · "}Residencia: <b>{POSTURE_MODE_LABELS[res.posture.mode as PostureMode] ?? res.posture.mode}</b>
              {res.posture.jurisdictions.length > 0 && ` (${res.posture.jurisdictions.join(", ")})`}</div>
            {res.result === "resolved" ? (
              <>
                <div className="flex items-center gap-2">
                  <StatusBadge tone="ok" dot>Se serviría con</StatusBadge>
                  <b>{res.destination_name ?? destName(res.destination_id ?? "")}</b>
                  {res.fidelity && <span className="text-text-tertiary">({res.fidelity === "native" ? "nativo" : "traducido"})</span>}
                </div>
                {res.substitution_reason && <div>Motivo de sustitución: {SKIP_REASONS[res.substitution_reason] ?? res.substitution_reason}</div>}
                {res.forced_masking && <div>Se fuerza el enmascarado por la residencia.</div>}
                {res.state !== "on" && <div className="text-text-tertiary">Con la política {res.state === "shadow" ? "en sombra solo se registraría" : "apagada no se aplicaría"}.</div>}
              </>
            ) : (
              <div className="flex items-center gap-2">
                <StatusBadge tone="danger" dot>Modelo no disponible</StatusBadge>
                <span>{UNAVAILABLE[res.kind ?? ""] ?? "No hay destino para este pedido."}</span>
              </div>
            )}
            {res.skipped.length > 0 && (
              <div>
                Descartados:
                <ul className="list-disc list-inside">
                  {res.skipped.map(s => <li key={s.destination_id}>{destName(s.destination_id)} — {SKIP_REASONS[s.reason] ?? s.reason}</li>)}
                </ul>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
};
