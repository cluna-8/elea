// Pestaña «Modelos»: lista única (propios + ofrecidos) con semáforo, alta, edición, ficha,
// activar/desactivar, archivar y ofertas por organización (operador).
import React, { useState } from "react";
import { Button, Card, StatusBadge, inputBaseClass, cn } from "../../../frontend/src/components/ui";
import { PROVIDER_LABELS } from "../redirect/catalog";
import { FieldErrors, parseOfferTenants } from "../redirect/helpers";
import { EmptyRow, Notice, ReasonDialog, tableClass, tdClass, thClass } from "../redirect/ui";
import { catalogApi } from "./api";
import { EntryFormFields } from "./EntryForm";
import {
  buildCreatePayload, buildPatchPayload, canEditSheet, canEnableEntry, canWriteEntry, CAPABILITY_LABELS, CredentialRow,
  EntryForm, entryStatus, entryToForm, EntryView, FEATURE_LABELS, FEATURES, isStale, levelLabel,
  newEntryForm, Permissions,
} from "./helpers";
import { SheetDialog } from "./SheetDialog";
import { Modal, ModalButtons, SemaforoBadge } from "./ui";

type Dialog =
  | { kind: "edit" | "archive" | "offers" | "sheet" | "enable"; entry: EntryView }
  | null;

const CreateEntry: React.FC<{
  perms: Permissions; credentials: CredentialRow[]; onDone: (msg: string) => void; onCancel: () => void;
}> = ({ perms, credentials, onDone, onCancel }) => {
  const [form, setForm] = useState<EntryForm>(newEntryForm());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const built = buildCreatePayload(form, { operator: perms.operator });
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    setApiError(null);
    try {
      await catalogApi.createEntry(built.payload);
      onDone(`Modelo «${form.name.trim()}» creado. Nace sin clasificar: completá la ficha de cumplimiento.`);
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setBusy(false);
      // la credencial tipeada no queda en memoria del formulario tras enviar
      setForm(f => ({ ...f, values: {} }));
    }
  };

  return (
    <Card title="Nuevo modelo" className="mb-6">
      {apiError && <Notice tone="error" onClose={() => setApiError(null)}>{apiError}</Notice>}
      <EntryFormFields form={form} setForm={setForm} errors={errors} perms={perms} credentials={credentials} />
      <div className="flex justify-end gap-2 mt-5">
        <Button variant="secondary" onClick={onCancel}>Cancelar</Button>
        <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Crear modelo"}</Button>
      </div>
    </Card>
  );
};

export const EditEntry: React.FC<{
  entry: EntryView; perms: Permissions; credentials: CredentialRow[]; onDone: (msg: string) => void; onCancel: () => void;
}> = ({ entry, perms, credentials, onDone, onCancel }) => {
  const [form, setForm] = useState<EntryForm>(() => entryToForm(entry));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const built = buildPatchPayload(form, entry, { operator: perms.operator });
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    setApiError(null);
    try {
      await catalogApi.patchEntry(entry.id, built.payload);
      onDone(`Modelo «${form.name.trim()}» actualizado.`);
    } catch (e) {
      setApiError((e as Error).message);
      setBusy(false);
      setForm(f => ({ ...f, values: {} }));
    }
  };

  return (
    <Modal title={`Editar «${entry.name}»`} onClose={onCancel}
      footer={<ModalButtons onCancel={onCancel} onSubmit={submit} submitLabel="Guardar cambios" busy={busy} />}>
      {apiError && <Notice tone="error" onClose={() => setApiError(null)}>{apiError}</Notice>}
      <EntryFormFields form={form} setForm={setForm} errors={errors} perms={perms} entry={entry} credentials={credentials} />
    </Modal>
  );
};

export const ModelsTab: React.FC<{
  perms: Permissions;
  entries: EntryView[];
  credentials: CredentialRow[];
  showArchived: boolean;
  setShowArchived: (v: boolean) => void;
  reload: () => Promise<void>;
}> = ({ perms, entries, credentials, showArchived, setShowArchived, reload }) => {
  const [creating, setCreating] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [tenantsText, setTenantsText] = useState("");

  const done = async (text: string) => {
    setDialog(null);
    setCreating(false);
    setMsg({ tone: "ok", text });
    await reload();
  };
  const fail = (e: unknown) => setMsg({ tone: "error", text: (e as Error).message });

  const toggleStatus = async (e: EntryView) => {
    try {
      await catalogApi.patchEntry(e.id, { status: e.status === "active" ? "inactive" : "active" });
      await done(e.status === "active" ? `«${e.name}» desactivado.` : `«${e.name}» activado.`);
    } catch (err) { fail(err); }
  };

  return (
    <div>
      {msg && <Notice tone={msg.tone} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      {creating ? (
        <CreateEntry perms={perms} credentials={credentials} onCancel={() => setCreating(false)} onDone={done} />
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <label className="inline-flex items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />
            Ver archivados
          </label>
          {perms.canAdmin && <Button onClick={() => setCreating(true)}>Nuevo modelo</Button>}
        </div>
      )}
      <Card noPadding title="Modelos disponibles">
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr>
              <th className={thClass}>Nombre</th><th className={thClass}>Proveedor · modelo</th>
              <th className={thClass}>Nivel</th><th className={thClass}>Estado</th>
              <th className={thClass}>Semáforo</th><th className={thClass}>Acciones</th>
            </tr></thead>
            <tbody>
              {entries.length === 0 && <EmptyRow cols={6}>Todavía no hay modelos en el catálogo.</EmptyRow>}
              {entries.map(e => {
                const st = entryStatus(e);
                const writable = canWriteEntry(perms, e);
                const featureList = FEATURES.filter(f => e.features?.[f]).map(f => FEATURE_LABELS[f]);
                return (
                  <tr key={e.id}>
                    <td className={tdClass}>
                      <div className="font-medium text-text-primary">{e.name}</div>
                      <div className="flex flex-wrap items-center gap-1 mt-0.5">
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
                      <div className="text-xs text-text-tertiary font-mono">{e.real_model}</div>
                      <div className="text-xs text-text-tertiary">
                        {CAPABILITY_LABELS[e.capability] ?? e.capability}
                        {e.context_window ? ` · ventana ${e.context_window.toLocaleString("es")}` : ""}
                        {featureList.length ? ` · ${featureList.join(", ")}` : ""}
                      </div>
                    </td>
                    <td className={tdClass}>
                      <div>{levelLabel(e.level)}</div>
                      {e.offered_to && (
                        <div className="text-xs text-text-tertiary">
                          Ofrecido a: {e.offered_to.length ? (e.offered_to.includes("*") ? "todas las organizaciones" : `${e.offered_to.length} organización(es)`) : "ninguna"}
                        </div>
                      )}
                    </td>
                    <td className={tdClass}><StatusBadge tone={st.tone} dot>{st.label}</StatusBadge></td>
                    <td className={tdClass}>
                      <SemaforoBadge semaforo={e.semaforo} />
                      {isStale(e) && <div className="text-xs text-warn mt-1">Ficha desactualizada</div>}
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
                        {canEnableEntry(perms, e) && (
                          <Button size="sm" variant="secondary" aria-label={`Habilitar ${e.name}`} onClick={() => setDialog({ kind: "enable", entry: e })}>Habilitar</Button>
                        )}
                        {writable && (
                          <Button size="sm" variant="danger" aria-label={`Archivar ${e.name}`} onClick={() => setDialog({ kind: "archive", entry: e })}>Archivar</Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {dialog?.kind === "sheet" && (
        <SheetDialog entry={dialog.entry} canEdit={canEditSheet(perms, dialog.entry)}
          onClose={() => setDialog(null)} onSaved={() => { void reload(); }} />
      )}
      {dialog?.kind === "edit" && (
        <EditEntry entry={dialog.entry} perms={perms} credentials={credentials}
          onCancel={() => setDialog(null)} onDone={done} />
      )}
      {dialog?.kind === "enable" && (
        <ReasonDialog
          title={`Habilitar «${dialog.entry.name}»`}
          description="Una regla de habilitación bloqueó este modelo. Habilitarlo exige un motivo y queda en el registro de cambios; no relaja la residencia."
          confirmLabel="Habilitar"
          onCancel={() => setDialog(null)}
          onConfirm={async reason => { await catalogApi.enableEntry(dialog.entry.id, reason); await done(`«${dialog.entry.name}» habilitado.`); }}
        />
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
              {/* TODO: elegir por nombre cuando la API de la consola liste los tenants (hoy no hay listado). */}
              <textarea className={cn(inputBaseClass, "h-20 py-2 border-border font-mono text-xs")}
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
