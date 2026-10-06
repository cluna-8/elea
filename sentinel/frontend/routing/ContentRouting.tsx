// Ruteo por contenido (auto-router semántico, spec 030): con «Auto» elegido, cada consulta se
// clasifica en esta máquina y va al modelo de la ruta ganadora. Extraído del panel de la pantalla
// de modelos de la base, sobre las mismas APIs (`/chat/router-config`, `/chat/router-config/...`).
// Solo administración edita; el resto lo ve en modo consulta (el backend aplica el permiso igual).
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Field, StatusBadge, Toggle, cn, inputBaseClass } from "../../../frontend/src/components/ui";
import { api, RouterConfig, RouterRoute } from "../../../frontend/src/services/api";
import { authStorage } from "../../../frontend/src/services/auth";
import { Notice } from "../redirect/ui";
import {
  erroresDeRuta, mezclarFrases, normalizarRouter, routerInvalido, rutaVacia, timeoutValido,
} from "./contentHelpers";

export const ContentRouting: React.FC = () => {
  const canEdit = useMemo(() => authStorage.getUser()?.role === "admin", []);
  const [cfg, setCfg] = useState<RouterConfig | null>(null);
  const [modelos, setModelos] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [abierta, setAbierta] = useState<number | null>(null);
  const [borrador, setBorrador] = useState<Record<number, string>>({});
  const [generando, setGenerando] = useState<number | null>(null);
  const [errorGeneracion, setErrorGeneracion] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    // Dos endpoints, dos fallos distintos: un catálogo caído no deja sin config, ni al revés.
    const [c, m] = await Promise.allSettled([api.getRouterConfig(), api.getModels()]);
    if (c.status === "fulfilled") {
      setCfg(normalizarRouter(c.value));
      setDirty(false);
      setBorrador({});
      setAbierta(null);
    } else {
      setError((c.reason as Error)?.message || "No se pudo cargar la configuración del ruteo inteligente.");
    }
    if (m.status === "fulfilled") {
      setModelos(m.value.filter((x: any) => x.provider !== "auto" && x.is_configured).map((x: any) => x.model_name));
    }
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const mutar = (fn: (c: RouterConfig) => RouterConfig) => {
    setCfg(prev => (prev ? fn(prev) : prev));
    setDirty(true);
    setOk("");
  };
  const mutarRuta = (i: number, cambios: Partial<RouterRoute>) =>
    mutar(c => ({ ...c, routes: c.routes.map((r, j) => (j === i ? { ...r, ...cambios } : r)) }));

  const agregarFrase = (i: number) => {
    const texto = (borrador[i] || "").trim();
    if (!texto) return;
    const actuales = cfg?.routes[i]?.utterances || [];
    if (!actuales.includes(texto)) mutarRuta(i, { utterances: [...actuales, texto] });
    setBorrador(p => ({ ...p, [i]: "" }));
  };

  const generar = async (i: number) => {
    const ruta = cfg?.routes[i];
    if (!ruta) return;
    setGenerando(i);
    setErrorGeneracion("");
    try {
      const generadas = await api.generateUtterances(ruta.name.trim(), (ruta.description || "").trim(), ruta.utterances);
      const nuevas = mezclarFrases(ruta.utterances, generadas);
      if (!nuevas.length) {
        setErrorGeneracion("El modelo no devolvió ninguna frase nueva. Probá con una descripción más específica.");
        return;
      }
      mutarRuta(i, { utterances: [...ruta.utterances, ...nuevas] });
    } catch (e) {
      setErrorGeneracion((e as Error)?.message || "No se pudieron generar frases de ejemplo.");
    } finally {
      setGenerando(null);
    }
  };

  const agregarRuta = () => {
    const i = cfg?.routes.length ?? 0;
    mutar(c => ({ ...c, routes: [...c.routes, rutaVacia(modelos[0] || "")] }));
    setAbierta(i);
    setErrorGeneracion("");
  };

  const eliminarRuta = (i: number) => {
    if (!confirm(`¿Eliminar la ruta "${cfg?.routes[i]?.name || "sin nombre"}"?`)) return;
    setBorrador({});
    setAbierta(prev => (prev === null || prev === i ? null : prev > i ? prev - 1 : prev));
    setErrorGeneracion("");
    mutar(c => ({ ...c, routes: c.routes.filter((_, j) => j !== i) }));
  };

  const guardar = async () => {
    if (!cfg) return;
    setSaving(true);
    setError("");
    setOk("");
    try {
      setCfg(normalizarRouter(await api.putRouterConfig(cfg)));
      setDirty(false);
      setBorrador({});
      setOk("Ruteo por contenido guardado. Aplica en la próxima consulta, sin reiniciar el motor IA.");
    } catch (e) {
      setError((e as Error)?.message || "No se pudo guardar la configuración del ruteo inteligente.");
    } finally {
      setSaving(false);
    }
  };

  const opciones = (sel: string) => (
    <>
      {sel && !modelos.includes(sel) && <option value={sel}>{sel} (ya no está en el catálogo)</option>}
      {modelos.map(n => <option key={n} value={n}>{n}</option>)}
    </>
  );

  const invalido = routerInvalido(cfg);

  return (
    <Card
      title="Ruteo por contenido"
      actions={canEdit && cfg ? (
        <>
          {dirty && <StatusBadge tone="warn">Cambios sin guardar</StatusBadge>}
          <Button variant="primary" size="sm" onClick={guardar} disabled={saving || loading || !dirty || invalido}>
            {saving ? "Guardando..." : "Guardar ruteo"}
          </Button>
          <div className="ml-1 flex items-center gap-2 border-l border-border pl-3">
            <span className="text-xs font-medium text-text-secondary">{cfg.enabled ? "Activo" : "Inactivo"}</span>
            <Toggle checked={cfg.enabled} onChange={v => mutar(c => ({ ...c, enabled: v }))} label="Ruteo automático" size="sm" />
          </div>
        </>
      ) : cfg ? <StatusBadge tone={cfg.enabled ? "ok" : "neutral"}>{cfg.enabled ? "Activo" : "Inactivo"}</StatusBadge> : null}
    >
      <p className="mb-4 text-xs leading-relaxed text-text-secondary">
        Con «Auto» elegido en el chat, cada consulta se clasifica en esta misma máquina (el texto no sale del servidor
        para decidir) y va al modelo de la ruta ganadora. Apagado, «Auto» se sirve siempre por el modelo por defecto.
      </p>
      {!canEdit && !loading && <Notice tone="info">Estás en modo consulta: solo administración puede editar el ruteo.</Notice>}
      {error && <Notice tone="error" onClose={() => setError("")}>{error}</Notice>}
      {ok && <Notice tone="ok" onClose={() => setOk("")}>{ok}</Notice>}
      {loading ? (
        <p className="py-8 text-center font-mono text-xs text-text-secondary">Cargando configuración de ruteo...</p>
      ) : !cfg ? (
        <div className="py-8 text-center text-xs text-text-secondary">
          No se pudo cargar la configuración del ruteo.{" "}
          <button className="text-primary underline" onClick={() => void load()}>Reintentar</button>
        </div>
      ) : (
        <div className="space-y-4">
          {cfg.config_error && (
            <div className="rounded-md border border-warn/30 bg-warn-bg px-4 py-2.5 text-xs leading-relaxed text-warn">
              <span className="font-semibold">Configuración de ruteo no legible.</span> El archivo del servidor falta o
              está corrupto, así que se muestran los valores por defecto (ruteo apagado, sin rutas). Al guardar se
              reescribe con lo que veas acá.
            </div>
          )}
          <fieldset disabled={!canEdit} className="grid min-w-0 gap-4 border-0 p-0 sm:grid-cols-2">
            <Field label="Modelo por defecto" hint="Se usa con el ruteo apagado, cuando ninguna ruta supera su umbral y cuando el ruteo falla.">
              <>
                <select
                  aria-label="Modelo por defecto"
                  value={cfg.default_model}
                  onChange={e => mutar(c => ({ ...c, default_model: e.target.value }))}
                  className={cn(inputBaseClass, "border-border")}
                >
                  <option value="">Elegir modelo…</option>
                  {opciones(cfg.default_model)}
                </select>
                {cfg.default_model && !cfg.default_model_ok && (
                  <StatusBadge tone="danger" className="self-start">«{cfg.default_model}» no está en el catálogo</StatusBadge>
                )}
              </>
            </Field>
            <Field
              label="Timeout del ruteo (segundos)"
              type="number" min={1} max={60} step={1}
              value={cfg.timeout_seconds}
              onChange={e => {
                const v = Number(e.target.value);
                mutar(c => ({ ...c, timeout_seconds: e.target.value === "" || !Number.isFinite(v) ? 0 : v }));
              }}
              error={timeoutValido(cfg.timeout_seconds) ? undefined : "Debe ser un número entre 1 y 60."}
              hint="Si la clasificación tarda más, la consulta se sirve por el modelo por defecto y queda registrada como ruteo degradado."
            />
          </fieldset>

          <p className="flex flex-wrap items-center gap-x-1.5 text-[11px] leading-relaxed text-text-secondary">
            <span className={cn("text-sm leading-none", cfg.embedding_model_ok ? "text-ok" : "text-danger")}>●</span>
            <span>Embeddings locales:</span>
            <span className="font-mono text-text-primary">{cfg.embedding_model || "sin configurar"}</span>
            <span className={cfg.embedding_model_ok ? undefined : "text-danger"}>
              {cfg.embedding_model_ok
                ? ": la clasificación corre en esta máquina."
                : "no disponible: falta en el catálogo del motor IA o en Ollama. Mientras tanto «Auto» va por el modelo por defecto."}
            </span>
          </p>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="min-w-0 text-[11px] leading-relaxed text-text-secondary">
                <span className="text-xs font-semibold text-text-primary">Rutas semánticas</span>
                {" · "}Gana la de mayor parecido que supere su propio umbral; con empate, la primera. Si ninguna llega, va al modelo por defecto.
              </p>
              {canEdit && <Button variant="secondary" size="sm" onClick={agregarRuta}>+ Agregar ruta</Button>}
            </div>
            {cfg.routes.length === 0 ? (
              <div className="rounded-md border border-dashed border-border py-6 text-center text-xs text-text-secondary">
                Sin rutas configuradas: «Auto» sirve siempre por el modelo por defecto.
              </div>
            ) : (
              <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
                {cfg.routes.map((ruta, i) => (
                  <RutaFila
                    key={i} i={i} ruta={ruta} abierta={abierta === i} canEdit={canEdit} opciones={opciones}
                    borrador={borrador[i] || ""} generando={generando} saving={saving} errorGeneracion={abierta === i ? errorGeneracion : ""}
                    onToggle={() => { setAbierta(abierta === i ? null : i); setErrorGeneracion(""); }}
                    onChange={c => mutarRuta(i, c)} onDelete={() => eliminarRuta(i)}
                    onBorrador={t => setBorrador(p => ({ ...p, [i]: t }))} onAgregarFrase={() => agregarFrase(i)}
                    onGenerar={() => void generar(i)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
};

interface RutaFilaProps {
  i: number; ruta: RouterRoute; abierta: boolean; canEdit: boolean;
  opciones: (sel: string) => React.ReactNode;
  borrador: string; generando: number | null; saving: boolean; errorGeneracion: string;
  onToggle: () => void; onChange: (c: Partial<RouterRoute>) => void; onDelete: () => void;
  onBorrador: (t: string) => void; onAgregarFrase: () => void; onGenerar: () => void;
}

const RutaFila: React.FC<RutaFilaProps> = ({
  i, ruta, abierta, canEdit, opciones, borrador, generando, saving, errorGeneracion,
  onToggle, onChange, onDelete, onBorrador, onAgregarFrase, onGenerar,
}) => {
  const [calibracion, setCalibracion] = useState(false);
  const errores = erroresDeRuta(ruta);
  const incompleta = Object.keys(errores).length > 0;
  const puedeGenerar = !!ruta.name.trim() && !!(ruta.description || "").trim();
  const generandoEsta = generando === i;
  const n = ruta.utterances.length;
  return (
    <div className={cn(abierta ? "bg-surface-2" : "bg-surface")}>
      <div className="flex items-center gap-2 px-3 py-1.5">
        <button type="button" onClick={onToggle} aria-expanded={abierta} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className="w-6 shrink-0 font-mono text-[10px] text-text-tertiary">#{i + 1}</span>
          {ruta.tier && <StatusBadge tone="neutral" className="shrink-0 uppercase">{ruta.tier}</StatusBadge>}
          <span className={cn("shrink-0 text-xs font-semibold", ruta.name.trim() ? "text-text-primary" : "text-text-tertiary")}>
            {ruta.name.trim() || "Ruta sin nombre"}
          </span>
          <span className="min-w-0 flex-1 truncate text-[11px] text-text-secondary">
            {ruta.description?.trim() ? `· ${ruta.description.trim()}` : ""}
          </span>
          <span className="shrink-0 text-[11px] text-text-secondary">
            → <span className={cn("font-mono", ruta.target_model ? "text-text-primary" : "text-danger")}>{ruta.target_model || "sin modelo"}</span>
          </span>
          <span className="shrink-0 text-[11px] text-text-tertiary">{n} {n === 1 ? "frase" : "frases"}</span>
          {ruta.target_ok === false && <StatusBadge tone="danger" className="shrink-0">Ruta rota</StatusBadge>}
          {!abierta && incompleta && <StatusBadge tone="warn" className="shrink-0">Incompleta</StatusBadge>}
        </button>
        {canEdit && (
          <Button variant="ghost" size="sm" onClick={onDelete} className="text-danger hover:bg-danger-bg hover:text-danger">
            Eliminar
          </Button>
        )}
      </div>

      {abierta && (
        <div className="space-y-3 border-t border-border px-3 py-3">
          <fieldset disabled={!canEdit} className="min-w-0 space-y-3 border-0 p-0">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem]">
            <Field label="Nombre" value={ruta.name} onChange={e => onChange({ name: e.target.value })}
              placeholder="ej: Código y análisis" error={errores.name} />
            <Field label="Modelo destino" error={errores.target}>
              <select aria-label="Modelo destino" value={ruta.target_model} onChange={e => onChange({ target_model: e.target.value })}
                className={cn(inputBaseClass, errores.target ? "border-danger" : "border-border")}>
                <option value="">Elegir modelo…</option>
                {opciones(ruta.target_model)}
              </select>
            </Field>
            <Field label="Umbral" type="number" min={0.05} max={1} step={0.05} value={ruta.score_threshold}
              hint="Parecido mínimo (0.05 a 1). Más alto, más exigente."
              onChange={e => {
                const v = Number(e.target.value);
                onChange({ score_threshold: e.target.value === "" || !Number.isFinite(v) ? 0 : v });
              }}
              error={errores.umbral} />
          </div>
          <Field label="Descripción" value={ruta.description || ""} onChange={e => onChange({ description: e.target.value })}
            placeholder="Para qué sirve esta ruta: de acá salen las frases de ejemplo" />
          </fieldset>

          <div className="rounded-md border border-border bg-surface">
            <button type="button" onClick={() => setCalibracion(v => !v)} aria-expanded={calibracion}
              className="flex w-full items-center gap-2 px-3 py-2 text-left">
              <span className="text-xs font-semibold text-text-primary">Calibración (frases de ejemplo)</span>
              <StatusBadge tone={errores.utterances ? "danger" : "neutral"}>{n} {n === 1 ? "frase" : "frases"}</StatusBadge>
              {errores.utterances && !calibracion && <span className="min-w-0 truncate text-[11px] text-danger">{errores.utterances}</span>}
              <span className="ml-auto text-[11px] text-text-tertiary">{calibracion ? "Ocultar" : "Abrir"}</span>
            </button>
            {calibracion && (
              <fieldset disabled={!canEdit} className="min-w-0 space-y-2 border-0 border-t border-border px-3 py-3">
                {canEdit && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span title={puedeGenerar ? "Redacta frases típicas con el modelo local." : "Escribí nombre y descripción primero"}>
                      <Button variant="primary" size="sm" onClick={onGenerar} disabled={!puedeGenerar || generando !== null || saving}>
                        {generandoEsta ? "Generando..." : "Generar ejemplos"}
                      </Button>
                    </span>
                    <span className="text-[11px] text-text-tertiary">Las escribe el modelo local a partir del nombre y la descripción. Puede tardar unos segundos.</span>
                  </div>
                )}
                {errorGeneracion && (
                  <div role="alert" className="rounded-md border border-danger/30 bg-danger-bg px-3 py-2 text-[11px] text-danger">{errorGeneracion}</div>
                )}
                {n > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {ruta.utterances.map((f, p) => (
                      <span key={`${p}-${f}`} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 py-0.5 text-[11px] text-text-primary">
                        {f}
                        <button type="button" aria-label={`Quitar la frase "${f}"`}
                          onClick={() => onChange({ utterances: ruta.utterances.filter((_, q) => q !== p) })}
                          className="leading-none text-text-tertiary hover:text-danger">×</button>
                      </span>
                    ))}
                  </div>
                )}
                <input
                  aria-label="Agregar frase de ejemplo"
                  value={borrador}
                  onChange={e => onBorrador(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); onAgregarFrase(); } }}
                  placeholder="¿Falta un caso? Escribilo y presioná Enter"
                  className={cn(inputBaseClass, "h-8 text-xs", errores.utterances ? "border-danger" : "border-border")}
                />
              </fieldset>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ContentRouting;
