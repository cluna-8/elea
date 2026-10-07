// Pestaña «Residencia»: región del perfil y su postura por defecto, relajaciones del enmascarado por destino
// (solo cumplimiento y super-admin las editan; 057 FR-023, FR-030, FR-031, FR-031a) y posturas por alcance
// (rige la más restrictiva) con la postura efectiva.
import React, { useState } from "react";
import { Button, Card, Field, StatusBadge, cn } from "../../../frontend/src/components/ui";
import { JURISDICTIONS, POSTURE_MODES, POSTURE_MODE_LABELS, PostureMode } from "./catalog";
import {
  buildPosturePayload, Destination, FieldErrors, Lookups, newPostureForm, Permissions, PostureRow, scopeLabel,
} from "./helpers";
import { DefaultPosture, MaskingRelaxation, redirectApi, RegionEffective } from "./api";
import { EmptyRow, Notice, ReasonDialog, ScopePicker, SelectField, tableClass, tdClass, thClass } from "./ui";

export interface EffectivePosture { mode: string; jurisdictions: string[]; explicit: boolean }

const modeLabel = (m: string) => POSTURE_MODE_LABELS[m as PostureMode] ?? m;

/** Texto neutro de cada valor de `default_posture` (nunca «Admisible» ni «Cumple»). */
export const DEFAULT_POSTURE_LABELS: Record<DefaultPosture, string> = {
  masked_all: "Enmascarado en todo destino",
  masked_offregion: "Enmascarado fuera de la región",
  reject_offregion: "Rechazar fuera de la región",
  allow: "Sin restricción",
  code_fallback: "Respaldo de seguridad: falta la región configurada",
};
const EDITABLE_POSTURES = ["masked_all", "masked_offregion", "reject_offregion", "allow"] as const;
const POSTURE_RANK: Record<string, number> = { allow: 0, masked_offregion: 2, reject_offregion: 2, masked_all: 3 };
/** Cambiar a una postura menos estricta quita el enmascarado forzado a algún destino: es la relajación por región. */
const relaxesMasking = (from: string, to: string) => (POSTURE_RANK[to] ?? 0) < (POSTURE_RANK[from] ?? 0);

const REVOKE_REASONS: Record<string, string> = {
  precondicion_incumplida: "la ficha del destino dejó de cumplir las precondiciones",
  destino_modificado: "el destino cambió (dirección, proveedor o modelo)",
};
const roleLabel = (r: string | null) =>
  r === "compliance_officer" ? "Cumplimiento" : r === "super_admin" ? "Super-admin" : "Administración";
const levelText = (l: string) => (l === "installation" ? "Instalación" : "Esta organización");

export const JurisdictionPicker: React.FC<{ value: string[]; onChange: (v: string[]) => void; error?: string }> = ({ value, onChange, error }) => (
  <fieldset>
    <legend className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-1.5">Jurisdicciones permitidas</legend>
    <div className="flex flex-wrap gap-2">
      {[...JURISDICTIONS, ...value.filter(v => !JURISDICTIONS.some(j => j.code === v)).map(code => ({ code, label: code }))].map(j => {
        const on = value.includes(j.code);
        return (
          <label key={j.code} title={j.label}
            className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs cursor-pointer",
              on ? "border-primary bg-primary-tint text-text-primary" : "border-border text-text-secondary")}>
            <input type="checkbox" className="sr-only" checked={on}
              onChange={() => onChange(on ? value.filter(v => v !== j.code) : [...value, j.code])} />
            {j.code === j.label ? j.code : `${j.code} · ${j.label}`}
          </label>
        );
      })}
    </div>
    {error && <p className="text-xs text-danger mt-1">{error}</p>}
  </fieldset>
);

const RegionCard: React.FC<{
  perms: Permissions;
  region: RegionEffective;
  reload: () => Promise<void>;
  onDone: (text: string) => void;
}> = ({ perms, region, reload, onDone }) => {
  const [open, setOpen] = useState(false);
  const [next, setNext] = useState<string>("");
  const row = region.region;
  const current = region.default_posture;
  const label = row?.name ?? null;
  const fallback = region.health !== "ok";

  const save = async (reason: string) => {
    if (!row) return;
    if (!next || next === row.default_posture) throw new Error("Elegí una postura distinta de la actual.");
    // El cumplimiento de una empresa no escribe la fila de instalación: su cambio es una fila de nivel empresa,
    // que gana solo para su organización (contracts/admin-api.md, «relajación por región»).
    if (row.level === "installation" && !perms.isSuper) {
      await redirectApi.createRegion({
        name: row.name, level: "tenant", jurisdictions: row.jurisdictions, region_profiles: row.region_profiles,
        default_posture: next, is_zone: row.is_zone, reason,
      });
    } else {
      await redirectApi.patchRegion(row.id, { default_posture: next, reason });
    }
    setOpen(false);
    onDone("Postura por defecto actualizada.");
    await reload();
  };

  return (
    <Card title="Región y postura por defecto" className="mb-6">
      {fallback && (
        <div role="alert" className="mb-3 rounded-md border border-warn/20 bg-warn-bg px-4 py-3 text-sm text-warn">
          {region.health === "region_unresolved"
            ? "Región de la instalación sin definir: todo lo redirigido se rechaza hasta que se configure."
            : `Falta la fila de región de esta instalación: rige el respaldo de seguridad. Todo lo redirigido sale enmascarado${
              region.jurisdictions.length ? ` y solo se permiten destinos dentro de ${region.jurisdictions.join(", ")}` : ""}.`}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {label && <b>{label}</b>}
        {label && <StatusBadge tone="info" dot>{`Dentro de ${label}`}</StatusBadge>}
        <span>Postura por defecto: <b>{DEFAULT_POSTURE_LABELS[current] ?? current}</b></span>
      </div>
      {region.jurisdictions.length > 0 && (
        <p className="text-xs text-text-tertiary mt-2">Jurisdicciones de la región: {region.jurisdictions.join(", ")}.</p>
      )}
      <p className="text-xs text-text-tertiary mt-1">
        Aplica a los pedidos redirigidos sin postura propia. La región es un criterio de riesgo, no una opinión de legalidad.
      </p>
      {perms.canManageRegion && row && (
        <div className="flex justify-end mt-3">
          <Button size="sm" variant="secondary" onClick={() => { setNext(row.default_posture); setOpen(true); }}>
            Cambiar postura por defecto
          </Button>
        </div>
      )}
      {open && row && (
        <ReasonDialog
          title="Cambiar la postura por defecto de la región"
          confirmLabel="Guardar"
          description="Solo cumplimiento y el super-admin lo cambian. Queda registrado con tu motivo."
          extra={(
            <div>
              <SelectField label="Nueva postura por defecto" value={next} onChange={setNext}
                options={EDITABLE_POSTURES.map(p => ({ value: p, label: DEFAULT_POSTURE_LABELS[p] }))} />
              {relaxesMasking(row.default_posture, next) && (
                <p className="text-xs text-warn mt-2">
                  Relajación por región: los destinos dentro de la región dejan de salir con el enmascarado forzado.
                  Es una decisión de cumplimiento y no la puede tomar el administrador de la organización.
                </p>
              )}
            </div>
          )}
          onCancel={() => setOpen(false)}
          onConfirm={save}
        />
      )}
    </Card>
  );
};

const RelaxationsCard: React.FC<{
  perms: Permissions;
  relaxations: MaskingRelaxation[];
  destinations: Destination[];
  reload: () => Promise<void>;
  onDone: (text: string) => void;
}> = ({ perms, relaxations, destinations, reload, onDone }) => {
  const [creating, setCreating] = useState(false);
  const [entryId, setEntryId] = useState("");
  const [level, setLevel] = useState("tenant");
  const [toRevoke, setToRevoke] = useState<MaskingRelaxation | null>(null);
  const active = new Set(relaxations.filter(r => !r.revoked_at).map(r => r.entry_id));
  const options = destinations.filter(d => !active.has(d.id));
  const canInstall = perms.isSuper && perms.canManageRegion;
  const nameOf = (r: MaskingRelaxation) => r.entry_name ?? destinations.find(d => d.id === r.entry_id)?.name ?? r.entry_id;

  return (
    <Card noPadding title="Relajaciones del enmascarado por destino" className="mb-6">
      <p className="px-4 pt-3 text-xs text-text-tertiary">
        Por defecto todo lo redirigido sale enmascarado. Cumplimiento puede quitar el enmascarado forzado a un destino
        concreto si su ficha tiene jurisdicciones de inferencia, entidad y control, retención cero y, en un agregador,
        la lista de proveedores. Nunca habilita un destino sin jurisdicción de inferencia.
      </p>
      {perms.canManageRegion && (
        <div className="flex justify-end px-4 pt-3">
          <Button size="sm" onClick={() => { setEntryId(""); setLevel("tenant"); setCreating(true); }}>Nueva relajación</Button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className={tableClass}>
          <thead><tr>
            <th className={thClass}>Destino</th><th className={thClass}>Nivel</th><th className={thClass}>Motivo</th>
            <th className={thClass}>Cargada por</th><th className={thClass}>Estado</th><th className={thClass}></th>
          </tr></thead>
          <tbody>
            {relaxations.length === 0 && <EmptyRow cols={6}>Sin relajaciones: todo lo redirigido sale enmascarado.</EmptyRow>}
            {relaxations.map(r => (
              <tr key={r.id}>
                <td className={tdClass}>{nameOf(r)}</td>
                <td className={tdClass}>{levelText(r.level)}</td>
                <td className={tdClass}>{r.reason}</td>
                <td className={tdClass}>{roleLabel(r.created_by_role)}</td>
                <td className={tdClass}>
                  {r.revoked_at
                    ? `Revocada: ${(r.revoke_reason && REVOKE_REASONS[r.revoke_reason]) ?? r.revoke_reason ?? "sin motivo"}`
                    : "Vigente"}
                </td>
                <td className={tdClass}>
                  {perms.canManageRegion && !r.revoked_at && (
                    <Button size="sm" variant="danger" onClick={() => setToRevoke(r)}>Revocar</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && (
        <ReasonDialog
          title="Nueva relajación por destino"
          confirmLabel="Crear relajación"
          description="El destino deja de salir con el enmascarado forzado. Queda registrado con tu motivo y se revoca sola si su ficha deja de cumplir las precondiciones."
          extra={(
            <div className="flex flex-col gap-3">
              <SelectField label="Destino" value={entryId} onChange={setEntryId} placeholder="Elegí…"
                options={options.map(d => ({ value: d.id, label: d.name }))} />
              <SelectField label="Nivel" value={level} onChange={setLevel}
                options={[{ value: "tenant", label: "Esta organización" },
                  ...(canInstall ? [{ value: "installation", label: "Instalación (todas las organizaciones)" }] : [])]} />
            </div>
          )}
          onCancel={() => setCreating(false)}
          onConfirm={async reason => {
            if (!entryId) throw new Error("Elegí el destino.");
            await redirectApi.createRelaxation({ entry_id: entryId, level, reason });
            setCreating(false);
            onDone("Relajación creada.");
            await reload();
          }}
        />
      )}
      {toRevoke && (
        <ReasonDialog
          title="Revocar la relajación"
          confirmLabel="Revocar" danger
          description="El destino vuelve a salir con el enmascarado forzado. La relajación queda en el historial."
          onCancel={() => setToRevoke(null)}
          onConfirm={async reason => {
            await redirectApi.revokeRelaxation(toRevoke.id, reason);
            setToRevoke(null);
            onDone("Relajación revocada.");
            await reload();
          }}
        />
      )}
    </Card>
  );
};

export const ResidencyTab: React.FC<{
  perms: Permissions;
  postures: PostureRow[];
  effective: EffectivePosture | null;
  lookups: Lookups;
  reload: () => Promise<void>;
  /** Región del perfil y su postura por defecto; `null` en un servidor sin esas rutas. */
  region?: RegionEffective | null;
  relaxations?: MaskingRelaxation[];
  destinations?: Destination[];
}> = ({ perms, postures, effective, lookups, reload, region = null, relaxations = [], destinations = [] }) => {
  const [form, setForm] = useState(newPostureForm());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [toDelete, setToDelete] = useState<PostureRow | null>(null);

  const submit = async () => {
    const built = buildPosturePayload(form, perms);
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    try {
      await redirectApi.createPosture(built.payload);
      setMsg({ tone: "ok", text: "Postura agregada." });
      setForm(newPostureForm());
      setOpen(false);
      await reload();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {msg && <Notice tone={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      {region && <RegionCard perms={perms} region={region} reload={reload} onDone={text => setMsg({ tone: "ok", text })} />}
      {region && (
        <RelaxationsCard perms={perms} relaxations={relaxations} destinations={destinations} reload={reload}
          onDone={text => setMsg({ tone: "ok", text })} />
      )}
      {effective && (
        <Card title="Postura efectiva para pedidos redirigidos (toda la organización)" className="mb-6">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <StatusBadge tone={effective.mode === "off" ? "warn" : "info"} dot>{modeLabel(effective.mode)}</StatusBadge>
            {effective.jurisdictions.length > 0 && <span>Jurisdicciones: <b>{effective.jurisdictions.join(", ")}</b></span>}
            <span className="text-text-tertiary">
              {effective.explicit ? "Surge de las filas cargadas." : "Por defecto: solo la región de la organización."}
            </span>
          </div>
        </Card>
      )}
      {perms.canAddPosture && !open && (
        <div className="flex justify-end mb-4"><Button onClick={() => {
          // «solo jurisdicciones permitidas» nace con las de la región efectiva (FR-030); el admin las acota
          setForm({ ...newPostureForm(), jurisdictions: region?.jurisdictions ?? [] });
          setOpen(true);
        }}>Agregar postura</Button></div>
      )}
      {open && (
        <Card title="Nueva postura" className="mb-6">
          {!perms.canManagePosture && (
            <Notice tone="info">
              Como administrador podés agregar posturas (nunca relajan: rige la más restrictiva).
              Editar o borrar es de cumplimiento.
            </Notice>
          )}
          <ScopePicker type={form.scope_type} value={form.scope_value} lookups={lookups} error={errors.scope_value}
            onChange={(scope_type, scope_value) => setForm({ ...form, scope_type, scope_value })} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <SelectField label="Modo" value={form.mode} onChange={v => setForm({ ...form, mode: v as PostureMode })}
              options={POSTURE_MODES.map(m => ({ value: m, label: POSTURE_MODE_LABELS[m] }))} />
            <Field label="Motivo" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} error={errors.reason} />
          </div>
          {form.mode !== "off" && (
            <div className="mt-4">
              <JurisdictionPicker value={form.jurisdictions} onChange={jurisdictions => setForm({ ...form, jurisdictions })} error={errors.jurisdictions} />
            </div>
          )}
          {perms.canManagePosture && (
            <label className="inline-flex items-center gap-2 text-sm mt-4">
              <input type="checkbox" checked={form.accept_foreign_entity}
                onChange={e => setForm({ ...form, accept_foreign_entity: e.target.checked })} />
              Aceptar destinos que infieren en región pero cuya entidad es de otra jurisdicción
            </label>
          )}
          {errors.accept_foreign_entity && <p className="text-xs text-danger mt-1">{errors.accept_foreign_entity}</p>}
          <div className="flex justify-end gap-2 mt-5">
            <Button variant="secondary" onClick={() => { setOpen(false); setErrors({}); }}>Cancelar</Button>
            <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Agregar"}</Button>
          </div>
        </Card>
      )}
      <Card noPadding title="Posturas cargadas">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Alcance</th><th className={thClass}>Modo</th><th className={thClass}>Jurisdicciones</th>
              <th className={thClass}>Motivo</th><th className={thClass}>Cargada por</th><th className={thClass}></th>
            </tr></thead>
            <tbody>
              {postures.length === 0 && <EmptyRow cols={6}>Sin posturas explícitas.</EmptyRow>}
              {postures.map(p => (
                <tr key={p.id}>
                  <td className={tdClass}>{scopeLabel(p.scope_type, p.scope_value, lookups)}</td>
                  <td className={tdClass}>{modeLabel(p.mode)}{p.accept_foreign_entity ? " · acepta entidad de otra jurisdicción" : ""}</td>
                  <td className={tdClass}>{p.jurisdictions.length ? p.jurisdictions.join(", ") : "—"}</td>
                  <td className={tdClass}>{p.reason}</td>
                  <td className={tdClass}>{p.created_by_role === "compliance_officer" ? "Cumplimiento" : p.created_by_role === "super_admin" ? "Super-admin" : "Administración"}</td>
                  <td className={tdClass}>
                    {perms.canManagePosture && <Button size="sm" variant="danger" onClick={() => setToDelete(p)}>Borrar</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {toDelete && (
        <ReasonDialog
          title="Borrar la postura"
          description="Borrar una postura puede relajar la residencia. Queda registrado con tu motivo."
          confirmLabel="Borrar" danger
          onCancel={() => setToDelete(null)}
          onConfirm={async reason => {
            await redirectApi.deletePosture(toDelete.id, reason);
            setToDelete(null);
            setMsg({ tone: "ok", text: "Postura borrada." });
            await reload();
          }}
        />
      )}
    </div>
  );
};
