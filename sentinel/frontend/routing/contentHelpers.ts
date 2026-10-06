// Funciones puras del ruteo por contenido (auto-router semántico, spec 030), extraídas del panel
// «Ruteo inteligente» de la pantalla de modelos de la base (sin tocarla). Sin React ni fetch.
import type { RouterConfig, RouterRoute } from "../../../frontend/src/services/api";

/** Config vacía servible: el panel siempre tiene una forma completa que editar aunque el GET
 *  devuelva un objeto parcial. */
export function normalizarRouter(cfg: any): RouterConfig {
  const rutas = Array.isArray(cfg?.routes) ? cfg.routes : [];
  return {
    enabled: !!cfg?.enabled,
    default_model: typeof cfg?.default_model === "string" ? cfg.default_model : "",
    timeout_seconds: typeof cfg?.timeout_seconds === "number" ? cfg.timeout_seconds : 5,
    embedding_model: typeof cfg?.embedding_model === "string" ? cfg.embedding_model : "",
    routes: rutas.map((r: any) => ({
      name: typeof r?.name === "string" ? r.name : "",
      description: typeof r?.description === "string" ? r.description : "",
      target_model: typeof r?.target_model === "string" ? r.target_model : "",
      score_threshold: typeof r?.score_threshold === "number" ? r.score_threshold : 0.45,
      tier: typeof r?.tier === "string" ? r.tier : "",
      utterances: Array.isArray(r?.utterances)
        ? r.utterances.filter((u: any) => typeof u === "string" && u.trim())
        : [],
      // Solo un `false` explícito señala rotura: sin el computado no se inventa una alarma.
      target_ok: r?.target_ok !== false,
    })),
    default_model_ok: cfg?.default_model_ok !== false,
    embedding_model_ok: cfg?.embedding_model_ok !== false,
    config_error: !!cfg?.config_error,
  };
}

export const timeoutValido = (t: number) => Number.isFinite(t) && t > 0 && t <= 60;

export interface ErroresRuta { name?: string; target?: string; umbral?: string; utterances?: string }

/** Espejo liviano de la validación del backend: señala el campo antes del viaje. La autoridad
 *  sigue siendo el PUT, que responde 422 con su detalle. */
export function erroresDeRuta(ruta: RouterRoute): ErroresRuta {
  const errores: ErroresRuta = {};
  if (!ruta.name?.trim()) errores.name = "El nombre es obligatorio.";
  if (!ruta.target_model?.trim()) errores.target = "Elegí el modelo destino.";
  if (!(ruta.score_threshold > 0 && ruta.score_threshold <= 1)) errores.umbral = "El umbral debe estar entre 0.05 y 1.";
  if (!ruta.utterances?.length) errores.utterances = "Generá o agregá al menos una frase de ejemplo.";
  return errores;
}

export const routerInvalido = (cfg: RouterConfig | null): boolean =>
  !!cfg && (!cfg.default_model.trim() || !timeoutValido(cfg.timeout_seconds)
    || cfg.routes.some(r => Object.keys(erroresDeRuta(r)).length > 0));

/** Suma frases nuevas a las existentes sin duplicar (espacios y mayúsculas no hacen frase nueva). */
export function mezclarFrases(actuales: string[], generadas: string[]): string[] {
  const vistas = new Set(actuales.map(u => u.trim().toLowerCase()));
  return generadas.filter(f => {
    const clave = f.trim().toLowerCase();
    if (!clave || vistas.has(clave)) return false;
    vistas.add(clave);
    return true;
  });
}

export const rutaVacia = (target: string): RouterRoute => ({
  name: "", description: "", target_model: target, score_threshold: 0.45, tier: "", utterances: [], target_ok: true,
});
