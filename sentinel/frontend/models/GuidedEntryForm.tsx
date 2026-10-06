// Alta guiada de modelos (spec 069, US8): proveedor con buscador → modelos con selección múltiple →
// credencial → confirmar (con el bloque «Avanzado» plegable). Las listas salen del motor a través del
// backend; si no responde, se carga a mano. El valor de una credencial es solo escritura: nunca se
// muestra y se borra del estado al enviar.
import React, { useEffect, useMemo, useState } from "react";
import { Button, Field, StatusBadge, cn, inputBaseClass } from "../../../frontend/src/components/ui";
import type { CredentialRow, Permissions } from "../catalog/helpers";
import { credentialOptionLabel } from "../catalog/helpers";
import { Modal, SecretFields } from "../catalog/ui";
import type { FieldErrors } from "../redirect/helpers";
import { Notice, SelectField } from "../redirect/ui";
import { modelsApi } from "./api";
import {
  BulkRow, buildBulkPayload, bulkRows, featureList, filterProviders, formatContext, formatFetchedAt, formatPrice,
  GuidedState, localProviders, newGuidedState, providerNeedsApiBase, ProviderInfo, RefModel, roleLabel, toFieldSpecs,
  toggleModel,
} from "./guided";

const STEPS = ["Proveedor", "Modelos", "Credencial", "Confirmar"] as const;
const PAGE = 50;
/** Errores que pertenecen al paso Credencial (para frenar el «Siguiente»). */
const isCredentialError = (k: string) => k === "credential" || k === "api_base" || k === "level" || k.startsWith("cred.");

const Stepper: React.FC<{ step: number }> = ({ step }) => (
  <ol className="mb-4 flex flex-wrap gap-2 text-xs" aria-label="Pasos del alta">
    {STEPS.map((label, i) => (
      <li key={label} aria-current={i === step ? "step" : undefined}
        className={cn("rounded-full px-3 py-1 font-semibold",
          i === step ? "bg-primary text-white" : i < step ? "bg-ok-bg text-ok" : "bg-surface-2 text-text-secondary")}>
        {i + 1}. {label}
      </li>
    ))}
  </ol>
);

export const GuidedEntryForm: React.FC<{
  perms: Permissions;
  credentials: CredentialRow[];
  onClose: () => void;
  /** Se llama al terminar (con al menos un modelo creado) para que la lista se recargue. */
  onDone: (msg: string) => void;
}> = ({ perms, credentials, onClose, onDone }) => {
  const [step, setStep] = useState(0);
  const [st, setSt] = useState<GuidedState>(() => newGuidedState());
  const [errors, setErrors] = useState<FieldErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<BulkRow[] | null>(null);

  // proveedores
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [available, setAvailable] = useState(true);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  const [loadingProviders, setLoadingProviders] = useState(true);
  const [providerQuery, setProviderQuery] = useState("");
  const [nonce, setNonce] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  // modelos
  const [modelQuery, setModelQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [models, setModels] = useState<RefModel[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, RefModel>>({});
  const [manualModel, setManualModel] = useState("");

  useEffect(() => {
    let alive = true;
    setLoadingProviders(true);
    modelsApi.providers()
      .then(r => {
        if (!alive) return;
        const list = r.data ?? [];
        setAvailable(r.available !== false && list.length > 0);
        setProviders(list.length ? list : localProviders());
        setFetchedAt(r.fetched_at ?? null);
      })
      .catch(() => {
        if (!alive) return;
        setAvailable(false);
        setProviders(localProviders());
      })
      .finally(() => { if (alive) setLoadingProviders(false); });
    return () => { alive = false; };
  }, [nonce]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(modelQuery), 250);
    return () => clearTimeout(t);
  }, [modelQuery]);

  const manual = !available || modelsError !== null;

  useEffect(() => {
    if (step !== 1 || !st.provider || !available) return;
    let alive = true;
    setLoadingModels(true);
    setModelsError(null);
    modelsApi.providerModels(st.provider, { q: debouncedQuery, limit: PAGE, offset: 0 })
      .then(r => {
        if (!alive) return;
        setModels(r.data ?? []);
        setTotal(r.total ?? (r.data ?? []).length);
        setSuggestions(prev => ({ ...prev, ...Object.fromEntries((r.data ?? []).map(m => [m.id, m])) }));
      })
      .catch(e => { if (alive) setModelsError((e as Error).message); })
      .finally(() => { if (alive) setLoadingModels(false); });
    return () => { alive = false; };
  }, [step, st.provider, debouncedQuery, available, nonce]);

  const loadMore = async () => {
    setLoadingModels(true);
    try {
      const r = await modelsApi.providerModels(st.provider, { q: debouncedQuery, limit: PAGE, offset: models.length });
      setModels(prev => [...prev, ...(r.data ?? [])]);
      setSuggestions(prev => ({ ...prev, ...Object.fromEntries((r.data ?? []).map(m => [m.id, m])) }));
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setLoadingModels(false);
    }
  };

  const refreshPrices = async () => {
    setRefreshing(true);
    setApiError(null);
    try {
      const r = await modelsApi.refreshReference();
      if (r?.fetched_at) setFetchedAt(r.fetched_at);
      setNonce(n => n + 1);
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const provider = providers.find(p => p.provider === st.provider);
  const fields = useMemo(() => toFieldSpecs(provider?.credential_fields ?? []), [provider]);
  const visibleProviders = useMemo(() => filterProviders(providers, providerQuery), [providers, providerQuery]);
  const set = (patch: Partial<GuidedState>) => setSt(s => ({ ...s, ...patch }));
  const usable = credentials.filter(c => c.status === "active" && c.level === st.level);
  const fetchedLabel = formatFetchedAt(fetchedAt);

  const pickProvider = (p: ProviderInfo) => {
    setModels([]); setTotal(0); setModelQuery(""); setDebouncedQuery(""); setModelsError(null); setSuggestions({});
    setSt(s => ({ ...newGuidedState(p.provider), level: s.level, credMode: p.credential_fields.some(f => f.required) ? "new" : "none" }));
    setErrors({});
  };

  const next = () => {
    const e: FieldErrors = {};
    if (step === 0 && !st.provider) e.provider = "Elegí un proveedor.";
    if (step === 1 && !st.selected.length) e.models = "Elegí al menos un modelo.";
    if (step === 2) {
      const dry = buildBulkPayload({ ...st, selected: st.selected.length ? st.selected : [{ real_model: "x", name: "", accept_suggestion: false }] },
        fields, { operator: perms.operator });
      for (const [k, v] of Object.entries(dry.errors)) if (isCredentialError(k)) e[k] = v;
    }
    setErrors(e);
    if (!Object.keys(e).length) setStep(s => s + 1);
  };

  const submit = async () => {
    const built = buildBulkPayload(st, fields, { operator: perms.operator });
    setErrors(built.errors);
    if (!built.payload) return;
    setBusy(true);
    setApiError(null);
    try {
      const body = await modelsApi.bulkCreate(built.payload);
      const result = bulkRows(body);
      setRows(result.length ? result : st.selected.map(m => ({ model: m.real_model, ok: true, message: "Creado" })));
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setBusy(false);
      // la credencial tipeada no queda en memoria del formulario tras enviar
      setSt(s => ({ ...s, values: {} }));
    }
  };

  const created = rows?.filter(r => r.ok).length ?? 0;
  const finish = () => {
    if (created > 0) onDone(`${created === 1 ? "1 modelo dado de alta" : `${created} modelos dados de alta`}. Nacen sin clasificar: completá la ficha de cumplimiento.`);
    else onClose();
  };

  const footer = rows ? (
    <Button onClick={finish}>Listo</Button>
  ) : (
    <>
      <Button variant="secondary" onClick={onClose} disabled={busy}>Cancelar</Button>
      {step > 0 && <Button variant="secondary" onClick={() => { setErrors({}); setStep(s => s - 1); }} disabled={busy}>Atrás</Button>}
      {step < STEPS.length - 1
        ? <Button onClick={next}>Siguiente</Button>
        : <Button onClick={submit} disabled={busy}>{busy ? "Guardando…" : `Dar de alta ${st.selected.length === 1 ? "1 modelo" : `${st.selected.length} modelos`}`}</Button>}
    </>
  );

  return (
    <Modal title="Dar de alta modelos" onClose={onClose} footer={footer}>
      {apiError && <Notice tone="error" onClose={() => setApiError(null)}>{apiError}</Notice>}
      {!rows && <Stepper step={step} />}
      {!rows && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="secondary" onClick={refreshPrices} disabled={refreshing}>
            {refreshing ? "Actualizando…" : "Actualizar precios"}
          </Button>
          <span className="text-xs text-text-tertiary">
            {fetchedLabel ? `Última actualización: ${fetchedLabel}` : "Todavía no se actualizaron los precios."}
          </span>
        </div>
      )}

      {rows ? (
        <ResultList rows={rows} />
      ) : step === 0 ? (
        <div className="flex flex-col gap-3">
          {!available && !loadingProviders && (
            <Notice tone="info">Las listas del motor no están disponibles: podés cargar el modelo a mano.</Notice>
          )}
          <Field label="Buscar proveedor" value={providerQuery} onChange={e => setProviderQuery(e.target.value)}
            placeholder="Anthropic, Azure, Ollama…" autoComplete="off" />
          {errors.provider && <p role="alert" className="text-xs text-danger">{errors.provider}</p>}
          {loadingProviders ? <p className="text-sm text-text-tertiary">Cargando proveedores…</p> : (
            <div role="radiogroup" aria-label="Proveedor" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {visibleProviders.length === 0 && <p className="text-sm text-text-tertiary">Ningún proveedor coincide con la búsqueda.</p>}
              {visibleProviders.map(p => (
                <label key={p.provider}
                  className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
                    st.provider === p.provider ? "border-primary bg-surface-2" : "border-border",
                    !p.supported && "opacity-60")}>
                  <input type="radio" name="guided-provider" className="mt-1" disabled={!p.supported}
                    checked={st.provider === p.provider} onChange={() => pickProvider(p)} />
                  <span className="flex flex-col">
                    <span className="font-medium text-text-primary">{p.display_name}</span>
                    {!p.supported && <span className="text-xs text-text-tertiary">{p.reason || "No soportado"}</span>}
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
      ) : step === 1 ? (
        <div className="flex flex-col gap-3">
          {modelsError && <Notice tone="info">No se pudo leer la lista de modelos del proveedor: podés cargar el modelo a mano.</Notice>}
          {!available && <Notice tone="info">Las listas del motor no están disponibles: podés cargar el modelo a mano.</Notice>}
          {errors.models && <p role="alert" className="text-xs text-danger">{errors.models}</p>}
          {manual ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-end gap-2">
                <Field className="flex-1" label="Modelo real" value={manualModel} onChange={e => setManualModel(e.target.value)}
                  hint={provider?.example_model ? `El nombre exacto en el proveedor, por ejemplo ${provider.example_model}.` : "El nombre exacto del modelo en el proveedor."} />
                <Button variant="secondary" onClick={() => {
                  const id = manualModel.trim();
                  if (id && !st.selected.some(m => m.real_model === id)) set({ selected: [...st.selected, { real_model: id, name: "", accept_suggestion: false }] });
                  setManualModel("");
                }}>Agregar modelo</Button>
              </div>
            </div>
          ) : (
            <>
              <Field label="Buscar modelo" value={modelQuery} onChange={e => setModelQuery(e.target.value)} autoComplete="off" />
              <p className="text-xs text-text-tertiary">Sugerido por el motor · se puede cambiar</p>
              {loadingModels && models.length === 0 && <p className="text-sm text-text-tertiary">Cargando modelos…</p>}
              {!loadingModels && models.length === 0 && <p className="text-sm text-text-tertiary">Ningún modelo coincide con la búsqueda.</p>}
              <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto" aria-label="Modelos del proveedor">
                {models.map(m => {
                  const price = formatPrice(m.price);
                  const ctx = formatContext(m);
                  const feats = featureList(m.features);
                  return (
                    <li key={m.id}>
                      <label className="flex items-start gap-2 rounded-md border border-border px-3 py-2 text-sm">
                        <input type="checkbox" className="mt-1" aria-label={m.id}
                          checked={st.selected.some(s => s.real_model === m.id)}
                          onChange={() => set({ selected: toggleModel(st.selected, m.id, true) })} />
                        <span className="flex flex-col gap-0.5">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs text-text-primary">{m.id}</span>
                            <StatusBadge tone="neutral">{roleLabel(m.role)}</StatusBadge>
                          </span>
                          {ctx && <span className="text-xs text-text-tertiary">{ctx}</span>}
                          {price && <span className="text-xs text-text-tertiary">{price}</span>}
                          {feats.length > 0 && <span className="text-xs text-text-tertiary">{feats.join(", ")}</span>}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              {models.length < total && (
                <Button variant="secondary" size="sm" onClick={loadMore} disabled={loadingModels}>
                  Ver más ({total - models.length} restantes)
                </Button>
              )}
            </>
          )}
          {st.selected.length > 0 && (
            <div aria-live="polite" className="text-sm text-text-secondary">
              Elegidos ({st.selected.length}): {st.selected.map(m => m.real_model).join(", ")}
              {manual && (
                <span className="ml-2">
                  {st.selected.map(m => (
                    <button key={m.real_model} type="button" className="mr-2 text-xs underline"
                      aria-label={`Quitar ${m.real_model}`}
                      onClick={() => set({ selected: toggleModel(st.selected, m.real_model) })}>Quitar {m.real_model}</button>
                  ))}
                </span>
              )}
            </div>
          )}
        </div>
      ) : step === 2 ? (
        <div className="flex flex-col gap-4">
          {perms.operator && (
            <SelectField label="Nivel" value={st.level}
              onChange={v => set({ level: v as GuidedState["level"], credentialId: "" })}
              options={[
                { value: "tenant", label: "Esta organización (clave propia)" },
                { value: "installation", label: "Instalación (se ofrece a organizaciones)" },
              ]} error={errors.level} />
          )}
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-text-primary">Credencial</legend>
            <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2 text-sm" role="radiogroup" aria-label="Origen de la credencial">
              {([
                ["existing", "Usar una credencial existente", true],
                ["new", "Cargar una credencial nueva", true],
                ["none", "Sin credencial", !fields.some(f => f.required)],
              ] as const).filter(m => m[2]).map(([mode, label]) => (
                <label key={mode} className="inline-flex items-center gap-2">
                  <input type="radio" name="guided-cred-mode" checked={st.credMode === mode} onChange={() => set({ credMode: mode })} />
                  {label}
                </label>
              ))}
            </div>
            {errors.credential && <p role="alert" className="mb-2 text-xs text-danger">{errors.credential}</p>}
            {st.credMode === "existing" && (
              <SelectField label="Credencial" value={st.credentialId} onChange={v => set({ credentialId: v })}
                options={usable.map(c => ({ value: c.id, label: credentialOptionLabel(c) }))}
                placeholder={usable.length ? "Elegí…" : "No hay credenciales de este nivel"} />
            )}
            {st.credMode === "new" && (
              <div className="flex flex-col gap-3">
                <Field label="Nombre de la credencial" value={st.newName} onChange={e => set({ newName: e.target.value })}
                  hint="Para reconocerla después; el valor no vuelve a mostrarse." />
                <SecretFields fields={fields} values={st.values} errors={errors} onChange={values => set({ values })} />
              </div>
            )}
            {st.credMode === "none" && <p className="text-sm text-text-tertiary">Estos modelos se usan sin credencial.</p>}
          </fieldset>
          <Field label={providerNeedsApiBase(st.provider) ? "Dirección base" : "Dirección base (opcional)"}
            value={st.apiBase} onChange={e => set({ apiBase: e.target.value })} error={errors.api_base} placeholder="https://…" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-text-secondary">
            {provider?.display_name ?? st.provider}: {st.selected.length === 1 ? "1 modelo" : `${st.selected.length} modelos`}.
            Nacen sin clasificar: la ficha de cumplimiento se completa después.
          </p>
          <ul className="flex flex-col gap-2">
            {st.selected.map(m => {
              const sug = suggestions[m.real_model];
              const hasSug = Boolean(sug && (sug.price || sug.max_input_tokens));
              return (
                <li key={m.real_model} className="rounded-md border border-border px-3 py-2">
                  <div className="font-mono text-xs text-text-primary">{m.real_model}</div>
                  <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <Field label={`Nombre de ${m.real_model} (opcional)`} value={m.name} placeholder="Se genera a partir del modelo"
                      onChange={e => set({ selected: st.selected.map(x => x.real_model === m.real_model ? { ...x, name: e.target.value } : x) })} />
                    {hasSug && (
                      <label className="inline-flex items-center gap-2 self-end text-sm text-text-primary">
                        <input type="checkbox" checked={m.accept_suggestion}
                          aria-label={`Usar lo sugerido para ${m.real_model}`}
                          onChange={e => set({ selected: st.selected.map(x => x.real_model === m.real_model ? { ...x, accept_suggestion: e.target.checked } : x) })} />
                        Usar el precio y el contexto sugeridos
                      </label>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
          <details className="rounded-md border border-border px-3 py-2">
            <summary className="cursor-pointer text-sm font-semibold text-text-primary">Avanzado</summary>
            <div className="mt-3 flex flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Parámetros libres (JSON)</span>
                <textarea aria-label="Parámetros libres (JSON)" spellCheck={false} autoComplete="off"
                  className={cn(inputBaseClass, "h-24 py-2 font-mono text-xs", errors.advanced ? "border-danger" : "border-border")}
                  value={st.advancedText} onChange={e => set({ advancedText: e.target.value })} placeholder='{"temperature": 0.2}' />
                {errors.advanced && <p role="alert" className="text-xs text-danger">{errors.advanced}</p>}
              </label>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {([
                  ["rpm", "Pedidos por minuto (solo informativo)"],
                  ["tpm", "Tokens por minuto (solo informativo)"],
                  ["max_parallel_requests", "Pedidos en paralelo (solo informativo)"],
                ] as const).map(([k, label]) => (
                  <Field key={k} label={label} inputMode="numeric" value={st.limits[k]} error={errors[`limits.${k}`]}
                    onChange={e => set({ limits: { ...st.limits, [k]: e.target.value } })} />
                ))}
                {([
                  ["timeout", "Tiempo de espera, en segundos (se aplica en cada pedido)"],
                  ["num_retries", "Reintentos (se aplican en cada pedido)"],
                ] as const).map(([k, label]) => (
                  <Field key={k} label={label} inputMode="numeric" value={st.limits[k]} error={errors[`limits.${k}`]}
                    onChange={e => set({ limits: { ...st.limits, [k]: e.target.value } })} />
                ))}
                <Field label="Modelo base (opcional)" value={st.baseModel} onChange={e => set({ baseModel: e.target.value })}
                  hint="Para tomar precios y capacidades de otro modelo." />
              </div>
            </div>
          </details>
        </div>
      )}
    </Modal>
  );
};

const ResultList: React.FC<{ rows: BulkRow[] }> = ({ rows }) => (
  <div>
    <h4 className="mb-2 text-sm font-semibold text-text-primary">Resultado por modelo</h4>
    <ul className="flex flex-col gap-2">
      {rows.map(r => (
        <li key={r.model} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-xs">{r.model}</span>
          <StatusBadge tone={r.ok ? "ok" : "danger"} dot>{r.ok ? "Creado" : "No se creó"}</StatusBadge>
          {!r.ok && <span className="text-xs text-text-secondary">{r.message}</span>}
        </li>
      ))}
    </ul>
  </div>
);
