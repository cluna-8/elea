// Pestaña «Modelos» de la pantalla única (spec 069, US7): UNA lista con las entradas del catálogo
// (semáforo, marca «Región UE», tipo, estado) y, debajo, los modelos heredados del motor que todavía
// no pasaron al catálogo. Alta guiada, edición, ficha, archivo y ofertas reutilizan los diálogos de
// `catalog/`. Los botones de escritura se muestran según el rol; el backend aplica los permisos igual.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, StatusBadge, cn, inputBaseClass } from "../../../frontend/src/components/ui";
import { catalogApi } from "../catalog/api";
import { EditEntry } from "../catalog/ModelsTab";
import {
  canEditSheet, canWriteEntry, CAPABILITY_LABELS, CredentialRow, entryStatus, EntryView, FEATURE_LABELS, FEATURES,
  isStale, levelLabel, Permissions,
} from "../catalog/helpers";
import { SheetDialog } from "../catalog/SheetDialog";
import { SemaforoBadge } from "../catalog/ui";
import { PROVIDER_LABELS } from "../redirect/catalog";
import { parseOfferTenants } from "../redirect/helpers";
import { EmptyRow, Notice, ReasonDialog, tableClass, tdClass, thClass } from "../redirect/ui";
import { CatalogStatus, LegacyModel, modelsApi } from "./api";
import { GuidedEntryForm } from "./GuidedEntryForm";
import { roleLabel } from "./guided";

/** La vista de la API suma `region_ue` (derivada de la jurisdicción de inferencia, separada del semáforo). */
export type ModelEntry = EntryView & { region_ue?: boolean | null };

type Dialog = { kind: "edit" | "archive" | "offers" | "sheet"; entry: ModelEntry } | null;

export const RegionBadge: React.FC<{ value: boolean | null | undefined }> = ({ value }) =>
  value === true ? <StatusBadge tone="ok" dot>Región UE</StatusBadge>
    : value === false ? <StatusBadge tone="neutral" dot>Fuera de la UE</StatusBadge>
      : <span className="text-xs text-text-tertiary">Región sin determinar</span>;

export const ModelsList: React.FC<{
  perms: Permissions;
  entries: ModelEntry[];
  credentials: CredentialRow[];
  showArchived: boolean;
  setShowArchived: (v: boolean) => void;
  reload: () => Promise<void>;
}> = ({ perms, entries, credentials, showArchived, setShowArchived, reload }) => {
  const [creating, setCreating] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [tenantsText, setTenantsText] = useState("");
  const [onlyEu, setOnlyEu] = useState(false);
  const [legacy, setLegacy] = useState<LegacyModel[]>([]);
  const [status, setStatus] = useState<CatalogStatus | null>(null);

  const loadLegacy = useCallback(async () => {
    setLegacy(await modelsApi.legacyModels());
    setStatus(await modelsApi.status());
  }, []);
  useEffect(() => { void loadLegacy(); }, [loadLegacy]);

  const done = async (text: string) => {
    setDialog(null);
    setCreating(false);
    setMsg({ tone: "ok", text });
    await Promise.all([reload(), loadLegacy()]);
  };
  const fail = (e: unknown) => setMsg({ tone: "error", text: (e as Error).message });

  const toggleStatus = async (e: ModelEntry) => {
    try {
      await catalogApi.patchEntry(e.id, { status: e.status === "active" ? "inactive" : "active" });
      await done(e.status === "active" ? `«${e.name}» desactivado.` : `«${e.name}» activado.`);
    } catch (err) { fail(err); }
  };

  const adopt = async (m: LegacyModel) => {
    try {
      await modelsApi.adoptLegacy(m.model_name);
      await done(`«${m.model_name}» pasó al catálogo. Nace sin clasificar: completá la ficha de cumplimiento.`);
    } catch (err) { fail(err); }
  };

  const adoptAll = async () => {
    try {
      const r = await modelsApi.adoptAll();
      await done(`${r.adopted} modelo(s) pasaron al catálogo${r.failed ? `; ${r.failed} no se pudieron pasar` : ""}. Nacen sin clasificar: completá sus fichas.`);
    } catch (err) { fail(err); }
  };

  const shown = useMemo(() => (onlyEu ? entries.filter(e => e.region_ue === true) : entries), [entries, onlyEu]);
  const shownLegacy = onlyEu ? [] : legacy;
  const colSpan = 7;

  return (
    <div>
      {msg && <Notice tone={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      {status && status.legacy_pending > 0 && (
        <Notice tone="info">
          Hay {status.legacy_pending} modelo(s) que todavía viven solo en la configuración del motor. Pasalos al
          catálogo para administrarlos acá, con su ficha, su credencial y el control por perfil.
          {perms.canAdmin && (
            <div className="mt-2"><Button size="sm" variant="secondary" onClick={adoptAll}>Pasar todos al catálogo</Button></div>
          )}
        </Notice>
      )}
      {status?.catalog_only && (
        <Notice tone="info">Los modelos se administran solo desde esta pantalla: la configuración del motor está en modo de solo lectura.</Notice>
      )}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />
            Ver archivados
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={onlyEu} onChange={e => setOnlyEu(e.target.checked)} />
            Solo región UE
          </label>
        </div>
        {perms.canAdmin && <Button onClick={() => setCreating(true)}>Dar de alta modelos</Button>}
      </div>

      <Card noPadding title="Modelos disponibles">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Nombre</th><th className={thClass}>Proveedor · modelo</th>
              <th className={thClass}>Tipo</th><th className={thClass}>Región</th>
              <th className={thClass}>Estado</th><th className={thClass}>Semáforo</th>
              <th className={thClass}>Acciones</th>
            </tr></thead>
            <tbody>
              {shown.length === 0 && shownLegacy.length === 0 && (
                <EmptyRow cols={colSpan}>
                  {onlyEu ? "Ningún modelo está marcado como región UE." : "Todavía no hay modelos en el catálogo."}
                </EmptyRow>
              )}
              {shown.map(e => {
                const st = entryStatus(e);
                const writable = canWriteEntry(perms, e);
                const featureList = FEATURES.filter(f => e.features?.[f]).map(f => FEATURE_LABELS[f]);
                return (
                  <tr key={e.id}>
                    <td className={tdClass}>
                      <div className="font-medium text-text-primary">{e.name}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1">
                        {e.is_aggregator && <StatusBadge tone="info">Agregador</StatusBadge>}
                        <span className="text-xs text-text-tertiary">
                          {e.has_credential
                            ? e.credential ? `Credencial: ${e.credential.name} · huella ${e.credential.fingerprint ?? "—"}` : "Credencial guardada"
                            : "Sin credencial"}
                        </span>
                      </div>
                    </td>
                    <td className={tdClass}>
                      <div>{PROVIDER_LABELS[e.provider] ?? e.provider}</div>
                      <div className="font-mono text-xs text-text-tertiary">{e.real_model}</div>
                      <div className="text-xs text-text-tertiary">
                        {CAPABILITY_LABELS[e.capability] ?? e.capability}
                        {e.context_window ? ` · ventana ${e.context_window.toLocaleString("es-AR")}` : ""}
                        {featureList.length ? ` · ${featureList.join(", ")}` : ""}
                      </div>
                    </td>
                    <td className={tdClass}>
                      <div>{roleLabel(e.role)}</div>
                      <div className="text-xs text-text-tertiary">{levelLabel(e.level)}</div>
                      {e.offered_to && (
                        <div className="text-xs text-text-tertiary">
                          Ofrecido a: {e.offered_to.length ? (e.offered_to.includes("*") ? "todas las organizaciones" : `${e.offered_to.length} organización(es)`) : "ninguna"}
                        </div>
                      )}
                    </td>
                    <td className={tdClass}><RegionBadge value={e.region_ue} /></td>
                    <td className={tdClass}><StatusBadge tone={st.tone} dot>{st.label}</StatusBadge></td>
                    <td className={tdClass}>
                      <SemaforoBadge semaforo={e.semaforo} />
                      {isStale(e) && <div className="mt-1 text-xs text-warn">Ficha desactualizada</div>}
                    </td>
                    <td className={tdClass}>
                      <div className="flex flex-wrap gap-1">
                        <Button size="sm" variant="secondary" aria-label={`Ficha de ${e.name}`} onClick={() => setDialog({ kind: "sheet", entry: e })}>Ficha</Button>
                        {writable && (
                          <Button size="sm" variant="secondary" aria-label={`Editar ${e.name}`} onClick={() => setDialog({ kind: "edit", entry: e })}>Editar</Button>
                        )}
                        {writable && (
                          <Button size="sm" variant="secondary" aria-label={`${e.status === "active" ? "Desactivar" : "Activar"} ${e.name}`}
                            onClick={() => toggleStatus(e)}>
                            {e.status === "active" ? "Desactivar" : "Activar"}
                          </Button>
                        )}
                        {perms.operator && e.level === "installation" && e.status !== "archived" && (
                          <Button size="sm" variant="secondary" aria-label={`Ofrecer ${e.name}`} onClick={() => {
                            setTenantsText((e.offered_to ?? []).join(", ")); setDialog({ kind: "offers", entry: e });
                          }}>Ofrecer</Button>
                        )}
                        {writable && (
                          <Button size="sm" variant="danger" aria-label={`Archivar ${e.name}`} onClick={() => setDialog({ kind: "archive", entry: e })}>Archivar</Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {shownLegacy.map(m => (
                <tr key={`legacy-${m.model_name}`}>
                  <td className={tdClass}>
                    <div className="font-medium text-text-primary">{m.model_name}</div>
                    <div className="mt-0.5"><StatusBadge tone="warn">Heredado del motor</StatusBadge></div>
                  </td>
                  <td className={tdClass}>
                    <div>{m.provider ? (PROVIDER_LABELS[m.provider as keyof typeof PROVIDER_LABELS] ?? m.provider) : "—"}</div>
                    {m.real_model && <div className="font-mono text-xs text-text-tertiary">{m.real_model}</div>}
                  </td>
                  <td className={tdClass}>{m.role ? roleLabel(m.role) : "—"}</td>
                  <td className={tdClass}><span className="text-xs text-text-tertiary">Región sin determinar</span></td>
                  <td className={tdClass}><StatusBadge tone="neutral" dot>Fuera del catálogo</StatusBadge></td>
                  <td className={tdClass}><span className="text-xs text-text-tertiary">Sin ficha</span></td>
                  <td className={tdClass}>
                    {perms.canAdmin && (
                      <Button size="sm" variant="secondary" aria-label={`Pasar ${m.model_name} al catálogo`} onClick={() => adopt(m)}>
                        Pasar al catálogo
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {creating && (
        <GuidedEntryForm perms={perms} credentials={credentials} onClose={() => setCreating(false)} onDone={done} />
      )}
      {dialog?.kind === "sheet" && (
        <SheetDialog entry={dialog.entry} canEdit={canEditSheet(perms, dialog.entry)}
          onClose={() => setDialog(null)} onSaved={() => { void reload(); }} />
      )}
      {dialog?.kind === "edit" && (
        <EditEntry entry={dialog.entry} perms={perms} credentials={credentials}
          onCancel={() => setDialog(null)} onDone={done} />
      )}
      {dialog?.kind === "archive" && (
        <ReasonDialog
          title={`Archivar «${dialog.entry.name}»`}
          description="El modelo deja de servir y sale de la lista. Para volver a usarlo hay que cargar uno nuevo."
          confirmLabel="Archivar" danger
          onCancel={() => setDialog(null)}
          onConfirm={async reason => { await catalogApi.archiveEntry(dialog.entry.id, reason); await done(`«${dialog.entry.name}» archivado.`); }}
        />
      )}
      {dialog?.kind === "offers" && (
        <ReasonDialog
          title={`Ofrecer «${dialog.entry.name}»`}
          description="Organizaciones que pueden usar este modelo. Retirar la oferta lo saca de esa organización."
          confirmLabel="Guardar oferta" reasonOptional
          extra={
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Organizaciones</span>
              <textarea className={cn(inputBaseClass, "h-20 border-border py-2 font-mono text-xs")}
                value={tenantsText} onChange={e => setTenantsText(e.target.value)} />
              <span className="text-xs text-text-tertiary">
                «*» = todas; si no, los identificadores de las organizaciones separados por coma. Vacío retira la oferta.
              </span>
            </label>
          }
          onCancel={() => setDialog(null)}
          onConfirm={async reason => {
            const parsed = parseOfferTenants(tenantsText);
            if (!parsed.tenants) throw new Error(parsed.error);
            await catalogApi.putOffers(dialog.entry.id, parsed.tenants, reason);
            await done(`Oferta de «${dialog.entry.name}» actualizada.`);
          }}
        />
      )}
    </div>
  );
};
