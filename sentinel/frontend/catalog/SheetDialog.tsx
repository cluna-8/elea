// Diálogo «Ficha» de cumplimiento: datos del proveedor que alimentan el semáforo. El semáforo es
// derivado: se muestra el que calcula el backend y no hay ningún control para editarlo.
import React, { useEffect, useState } from "react";
import { Button, Field, inputBaseClass, cn } from "../../../frontend/src/components/ui";
import { FieldErrors } from "../redirect/helpers";
import { Notice, SelectField } from "../redirect/ui";
import { catalogApi } from "./api";
import {
  buildSheetPayload, dpaLabel, DpaRow, EntryView, isStale, jurisdictionOptions, SheetForm, sheetToForm, Tri, TRI_LABELS,
  TRANSFER_LABELS, TRANSFER_MECHANISMS, suggestDpa,
} from "./helpers";
import { Modal, SemaforoBadge } from "./ui";

const TRI_OPTIONS = (["unknown", "yes", "no"] as Tri[]).map(t => ({ value: t, label: TRI_LABELS[t] }));

export const SheetDialog: React.FC<{
  entry: EntryView;
  canEdit: boolean;
  onClose: () => void;
  /** Se llama tras guardar, con la vista nueva (para refrescar la lista sin cerrar el diálogo). */
  onSaved: (entry: EntryView) => void;
}> = ({ entry, canEdit, onClose, onSaved }) => {
  const [current, setCurrent] = useState(entry);
  const [form, setForm] = useState<SheetForm>(() => sheetToForm(entry.sheet));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dpas, setDpas] = useState<DpaRow[]>([]);
  const ro = !canEdit;
  useEffect(() => {
    let vivo = true;
    catalogApi.dpas().then(r => { if (vivo) setDpas(r); }).catch(() => { /* sin lista: queda «Sin DPA» y el actual */ });
    return () => { vivo = false; };
  }, []);
  const sugerido = form.dpa_registry_id ? null : suggestDpa(current.provider, dpas);
  const set = (patch: Partial<SheetForm>) => { setSaved(false); setForm({ ...form, ...patch }); };

  const submit = async () => {
    const built = buildSheetPayload(form, current);
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    setApiError(null);
    try {
      const next = await catalogApi.putSheet(current.id, built.payload);
      setCurrent(next);
      setForm(sheetToForm(next.sheet));
      setSaved(true);
      onSaved(next);
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Ficha de «${current.name}»`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cerrar</Button>
          {canEdit && <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : "Guardar ficha"}</Button>}
        </>
      }
    >
      {apiError && <Notice tone="error" onClose={() => setApiError(null)}>{apiError}</Notice>}
      {isStale(current) && (
        <Notice tone="info">
          La ficha está desactualizada: cambió el proveedor o el modelo real desde que se clasificó. Revisá los datos y guardala de nuevo para recalcular el semáforo.
        </Notice>
      )}
      {ro && <Notice tone="info">Estás en modo consulta: la ficha solo puede editarla administración o cumplimiento.</Notice>}
      <div className="mb-4 rounded-md border border-border bg-surface-2 px-4 py-3" aria-live="polite">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">
          {saved ? "Semáforo recalculado" : "Semáforo"}
        </div>
        <SemaforoBadge semaforo={current.semaforo} detail />
        <p className="mt-2 text-xs text-text-tertiary">Se calcula a partir de la ficha; no se edita a mano.</p>
        {current.is_aggregator && (
          <p className="mt-1 text-xs text-text-tertiary">
            Este modelo es un agregador: la ficha cubre solo su capa, no al proveedor final.
          </p>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Entidad legal del proveedor" value={form.provider_legal_entity} disabled={ro}
          onChange={e => set({ provider_legal_entity: e.target.value })} error={errors.provider_legal_entity} />
        <SelectField label="Jurisdicción de la entidad" value={form.entity_jurisdiction} disabled={ro}
          onChange={v => set({ entity_jurisdiction: v })} placeholder="Sin declarar"
          options={jurisdictionOptions({ extra: form.entity_jurisdiction || null }).filter(o => o.value !== "unknown")} />
        <SelectField label="Jurisdicción de inferencia" value={form.inference_jurisdiction} disabled={ro}
          onChange={v => set({ inference_jurisdiction: v })}
          options={jurisdictionOptions({ extra: form.inference_jurisdiction })}
          hint="Dónde se procesan los datos al responder." />
        <SelectField label="Jurisdicción de registros" value={form.logs_jurisdiction} disabled={ro}
          onChange={v => set({ logs_jurisdiction: v })}
          options={jurisdictionOptions({ none: true, extra: form.logs_jurisdiction })}
          hint="Dónde se guardan los registros del proveedor." />
        <SelectField label="Retención cero" value={form.zero_data_retention} disabled={ro}
          onChange={v => set({ zero_data_retention: v as Tri })} options={TRI_OPTIONS} />
        <SelectField label="Entrena con datos" value={form.trains_on_data} disabled={ro}
          onChange={v => set({ trains_on_data: v as Tri })} options={TRI_OPTIONS} />
        <SelectField label="Mecanismo de transferencia" value={form.transfer_mechanism} disabled={ro}
          onChange={v => set({ transfer_mechanism: v })}
          options={TRANSFER_MECHANISMS.map(m => ({ value: m, label: TRANSFER_LABELS[m] }))} />
        <SelectField label="DPA asociado" value={form.dpa_registry_id} disabled={ro}
          onChange={v => set({ dpa_registry_id: v })} error={errors.dpa_registry_id}
          options={[
            { value: "", label: "— Ninguno —" },
            ...dpas.map(d => ({ value: d.id, label: dpaLabel(d) + (sugerido?.id === d.id ? " — sugerido" : "") })),
            ...(form.dpa_registry_id && !dpas.some(d => d.id === form.dpa_registry_id)
              ? [{ value: form.dpa_registry_id, label: "DPA actual (no listado)" }] : []),
          ]}
          hint={sugerido
            ? `El registro tiene un DPA de ${sugerido.provider_name}: elegilo si corresponde a este modelo.`
            : "Se elige del registro de DPAs (Cumplimiento). Su vigencia y región pesan en el semáforo."} />
        {current.is_aggregator && (
          <SelectField label="Región UE contratada" value={form.eu_region_contracted} disabled={ro}
            onChange={v => set({ eu_region_contracted: v as Tri })} options={TRI_OPTIONS}
            hint="Solo para agregadores: ¿hay región UE contratada con enrutamiento restringido?" />
        )}
        <label className="flex flex-col gap-1.5 md:col-span-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Notas</span>
          <textarea className={cn(inputBaseClass, "h-20 py-2 border-border")} value={form.notes} disabled={ro}
            onChange={e => set({ notes: e.target.value })} />
        </label>
      </div>
      {current.sheet.classified_at && (
        <p className="mt-3 text-xs text-text-tertiary">
          Última clasificación: {new Date(current.sheet.classified_at).toLocaleString("es")}.
        </p>
      )}
    </Modal>
  );
};
