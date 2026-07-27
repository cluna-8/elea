import React, { useState, useEffect } from "react";
import { api, ApiError, GovernanceLayerStatus, SecurityPolicy } from "../services/api";
import { EstadoBadge } from "./GovernancePage";
import { Card, PageHeader, StatusBadge, Button, Toggle, Field, inputBaseClass, cn } from "../components/ui";

const GUARDIAN_DESCRIPTIONS: Record<string, string> = {
  pii_masking: "Enmascaramiento local por expresiones regulares. Detecta DNI, CUIL, emails, teléfonos y personas sin depender de servicios externos.",
  secret_detection: "Detecta claves de API o tokens de seguridad y los redacta antes de enviarlos al modelo.",
  sensitive_routing: "Enruta prompts con términos sensibles a un modelo local on-premise de forma transparente.",
  presidio: "Detección NLP real de PII/PHI mediante el motor NLP del gateway (modelos de lenguaje, no regex). Requiere los dos microservicios del motor NLP (analyzer y anonymizer).",
  openai_moderation: "Filtro de contenido: detecta odio, acoso, autolesiones, violencia y contenido sexual.",
  lakera_prompt_injection: "Defensa en tiempo real contra ataques de jailbreak e inyecciones de prompts adversarias.",
  azure_content_safety: "Clasificación y mitigación de contenido inapropiado mediante filtros de seguridad en la nube.",
  llamaguard_moderations: "Escudo anti-jailbreak que analiza el prompt antes de enviarlo al modelo.",
  bedrock_guardrails: "Aplicación de temas prohibidos y filtros de seguridad corporativos en las peticiones.",
};

const GUARDIAN_ICONS: Record<string, string> = {
  pii_masking: "⬡",
  secret_detection: "◈",
  sensitive_routing: "⇄",
  presidio: "⬡",
  openai_moderation: "◉",
  lakera_prompt_injection: "⚡",
  azure_content_safety: "◈",
  llamaguard_moderations: "◉",
  bedrock_guardrails: "◈",
};

const LOCAL_TYPES = new Set(["pii_masking", "secret_detection", "sensitive_routing"]);

// Enlace LÓGICO guardián → capa de gobernanza (data-model §2.4: nunca FK, resuelto en
// query del lado del servidor y por esta tabla del lado del cliente). Las claves son los
// `guardian_type` que ya devuelve la API —los mismos que indexan los textos e íconos de
// arriba—: son identificadores internos de join, no copy, y no se renderizan nunca.
// Un tipo sin correspondencia NO se asume activo: cae a "estado desconocido" explícito.
const GUARDIAN_TYPE_TO_LAYER: Record<string, string> = {
  pii_masking: "pii_masking",
  presidio: "pii_masking",
  secret_detection: "secret_detection",
  sensitive_routing: "sensitive_routing",
  openai_moderation: "content_moderation",
  lakera_prompt_injection: "prompt_injection",
  llamaguard_moderations: "prompt_injection",
  azure_content_safety: "content_safety",
  bedrock_guardrails: "provider_guardrails",
};

// Clases de control reutilizables (consumen tokens, sin hex hardcodeado).
const controlCls = cn(inputBaseClass, "border-border");
const textareaCls =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary " +
  "placeholder:text-text-tertiary transition-colors resize-none focus:outline-none focus:ring-2 " +
  "focus:ring-primary focus:ring-offset-2 focus:ring-offset-canvas";
const labelText = "text-xs font-semibold uppercase tracking-wide text-text-secondary";

/** Resultado de "¿este interruptor se puede tocar?". Cuando NO se puede, viaja el copy
 *  junto a la decisión: un control bloqueado sin explicación es otra forma de mentir —el
 *  admin cree que la pantalla está rota, no que la capa es innegociable. */
/** Tipo PLANO a propósito, no un union discriminado por `habilitado`. Con
 *  `strictNullChecks` apagado (tsconfig.json, decisión documentada allá) TypeScript ensancha
 *  los literales `true`/`false` a `boolean` y el discriminante deja de narrowear, así que
 *  `control.motivo` no compilaba en las ramas donde sí existe. Aplanarlo cuesta dos campos
 *  vacíos en el caso habilitado y elimina la clase de error entera. */
type ControlDeseo = {
  habilitado: boolean;
  esPiso: boolean;
  /** Texto del botón cuando está bloqueado; vacío cuando se puede tocar. */
  etiqueta: string;
  /** Por qué no se puede tocar; vacío cuando se puede. */
  motivo: string;
};

/** Badge de estado desconocido. Existe para que la ausencia de dato tenga forma propia:
 *  la alternativa —caer a "Activo"— es exactamente la mentira que la 027 elimina. */
function EstadoDesconocido({ motivo }: { motivo: string }) {
  return (
    <StatusBadge tone="neutral" title={motivo} className="text-[10px] font-bold">
      <span aria-hidden="true" className="leading-none">?</span>
      Estado desconocido
    </StatusBadge>
  );
}

export const SecurityPage: React.FC = () => {
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [guardians, setGuardians] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<{ blocked: boolean; reason: string | null } | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  // FR-008: el toggle de Headroom auto-guarda al instante (optimista con revert). Este
  // estado sostiene el aviso cuando la persistencia falla y hubo que revertir.
  const [headroomError, setHeadroomError] = useState<string | null>(null);
  // Estado REAL por capa (spec 027): la única fuente de "esto se está aplicando". El
  // `is_active` del guardián es el DESEO y se rotula como tal.
  const [estadoPorCapa, setEstadoPorCapa] = useState<Record<string, GovernanceLayerStatus>>({});
  const [estadoNoDisponible, setEstadoNoDisponible] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Tercer estado explícito: "todavía no sé". El mapa vacío inicial es indistinguible de
  // "gobernanza respondió y no trajo capas", y de esa ambigüedad salía una ventana en la
  // que los interruptores de piso se podían tocar antes de que llegara el `tier`.
  const [estadoCargando, setEstadoCargando] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [policyData, guardiansData] = await Promise.all([
          api.getSecurityPolicy(),
          api.getGuardians(),
        ]);
        setPolicy(policyData);
        setGuardians(guardiansData);
      } catch (e: any) {
        // Antes esto era `catch { // silent }`: con /guardians admin-only, un
        // compliance_officer entraba por el nav y veía un grid vacío sin explicación —
        // un problema de permisos que parecía un producto roto.
        setLoadError(
          e?.message || "No se pudo cargar la configuración de seguridad. Verificá la conexión y tus permisos."
        );
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    // Consulta aparte y tolerante a fallo: el estado real es admin-only, así que un rol sin
    // permiso debe seguir viendo la configuración — pero con los estados como DESCONOCIDOS,
    // jamás como activos.
    (async () => {
      try {
        // Un modo concreto (`gateway-models`), no el resumen sin params: éste devuelve la unión de
        // los dos modos (cada `layer_key` repetido), y el `porCapa[...] = layer` de abajo se quedaba
        // con el ÚLTIMO por orden de iteración — un estado elegido por casualidad. `gateway-models`
        // es el modo donde NUESTRAS capas corren (sin upstream que delegue), así el badge del
        // guardián refleja si de verdad se está aplicando.
        const status = await api.getGovernanceStatus({ mode: "gateway-models" });
        const porCapa: Record<string, GovernanceLayerStatus> = {};
        for (const layer of status.layers) porCapa[layer.layer_key] = layer;
        setEstadoPorCapa(porCapa);
        setEstadoNoDisponible(null);
      } catch (e: any) {
        setEstadoPorCapa({});
        setEstadoNoDisponible(
          e instanceof ApiError && e.isForbidden
            ? "Tu rol no puede consultar el estado real de las capas: se muestra como desconocido, nunca como activo."
            : "No se pudo consultar el estado real de las capas. Lo que ves abajo es la configuración deseada, no lo que se está aplicando."
        );
      } finally {
        setEstadoCargando(false);
      }
    })();
  }, []);

  /** Estado real del guardián, vía su capa. `null` = no se puede afirmar nada. */
  const estadoDe = (guardianType: string): GovernanceLayerStatus | null => {
    const layerKey = GUARDIAN_TYPE_TO_LAYER[guardianType];
    if (!layerKey) return null;
    return estadoPorCapa[layerKey] || null;
  };

  /** ¿Se puede apagar esta capa DESDE ESTA PANTALLA?
   *
   *  El `tier` sale del catálogo real que expone gobernanza (`GET /governance/status`
   *  devuelve `tier: 'floor'|'optional'` por capa, contrato api-gobernanza.md), NUNCA de una
   *  lista de claves escrita acá: el catálogo es una constante del backend (D1) y una copia
   *  en el frontend se desincroniza en el primer alta de capa, justo del lado peligroso —
   *  una capa de piso nueva quedaría con interruptor vivo.
   *
   *  Por qué existe esta función: `PUT /guardians/<id>` con `is_active:false` sobre una capa
   *  de piso devuelve 200 y persiste, pero el pedido la sigue ejecutando porque el call-site
   *  fuerza el piso (`override_secret_detection=True`, SC-004). Es decir: la pantalla
   *  mostraba "apagado" sobre algo que corre. La 027 no admite ninguna de las dos mentiras
   *  —ni "activo" sobre lo que no corre, ni "apagado" sobre lo que sí—, y el backend de
   *  guardianes no se puede tocar en este PR, así que el control se saca de la UI.
   *
   *  Fail-closed en las tres formas de no saber (cargando, error de gobernanza, capa sin
   *  correspondencia en la respuesta): se bloquea y se dice que no se pudo verificar. Dejar
   *  apagar "por las dudas" es exactamente el caso que se está arreglando.
   */
  const controlDeseo = (guardianType: string, isActive: boolean): ControlDeseo => {
    if (estadoCargando) {
      return {
        habilitado: false,
        esPiso: false,
        etiqueta: "Verificando…",
        motivo:
          "Todavía no se sabe si esta capa pertenece al piso no negociable. El interruptor se " +
          "habilita recién cuando gobernanza confirma que es una capa opcional.",
      };
    }
    const estado = estadoDe(guardianType);
    if (!estado) {
      return {
        habilitado: false,
        esPiso: false,
        etiqueta: "Sin verificar",
        motivo:
          (estadoNoDisponible ? `${estadoNoDisponible} ` : "") +
          "Sin el estado de gobernanza no se puede verificar si esta capa es del piso, así que " +
          `no se permite apagarla desde acá. Configuración guardada: ${isActive ? "activada" : "desactivada"}.`,
      };
    }
    if (estado.tier === "floor") {
      return {
        habilitado: false,
        esPiso: true,
        etiqueta: "Siempre activo",
        motivo:
          "Piso no negociable: interceptar y registrar el tráfico, detectar datos personales y " +
          "bloquear secretos se aplican siempre, en todos los modos y superficies. Ninguna " +
          "configuración los desactiva —cualquier intento se rechaza y queda registrado—, por " +
          "eso acá no hay interruptor. El detalle, en la sección Gobernanza.",
      };
    }
    return { habilitado: true, esPiso: false, etiqueta: "", motivo: "" };
  };

  const handleToggleGuardian = (id: string, control: ControlDeseo) => {
    // El `disabled` del botón es cosmético —igual que el gating del nav—: la regla vive acá,
    // para que ningún camino de re-render deje pasar un cambio sobre una capa de piso.
    if (!control.habilitado) return;
    setGuardians((prev) => prev.map((g) => (g.id === id ? { ...g, is_active: !g.is_active } : g)));
  };

  const handleGuardianConfigChange = (id: string, key: string, value: any) => {
    setGuardians((prev) =>
      prev.map((g) => (g.id === id ? { ...g, config: { ...g.config, [key]: value } } : g))
    );
  };

  const handleGuardianFieldChange = (id: string, field: string, value: any) => {
    setGuardians((prev) => prev.map((g) => (g.id === id ? { ...g, [field]: value } : g)));
  };

  const handleSave = async () => {
    if (!policy) return;
    try {
      setSaving(true);
      await api.updateSecurityPolicy(policy);
      for (const g of guardians) {
        await api.updateGuardian(g.id, {
          name: g.name,
          guardian_type: g.guardian_type,
          is_active: g.is_active,
          config: g.config,
          fail_mode: g.fail_mode,
          apply_on: g.apply_on,
        });
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      alert("Error al guardar la configuración de seguridad.");
    } finally {
      setSaving(false);
    }
  };

  /** FR-008 — auto-guardado del toggle de Headroom.
   *  Antes este toggle solo mutaba el estado local y dependía del botón "Guardar Cambios"
   *  aparte, que el usuario olvidaba: reload = cambio perdido. Ahora persiste en el mismo
   *  `onChange`, de forma optimista: refleja el nuevo valor al instante, dispara el handler
   *  de guardado existente (`api.updateSecurityPolicy`, sin endpoint nuevo) y, si falla,
   *  revierte al valor previo y avisa. El botón "Guardar Cambios" se mantiene porque además
   *  persiste los guardianes y el resto de la config del panel. */
  const guardarHeadroom = async (checked: boolean) => {
    if (!policy) return;
    const previo = policy;
    const siguiente = { ...policy, headroom_mode: checked };
    // Optimista: la UI refleja el nuevo estado antes de que responda el servidor.
    setPolicy(siguiente);
    setHeadroomError(null);
    try {
      await api.updateSecurityPolicy(siguiente);
    } catch {
      // Revert + aviso: nunca dejamos la UI mostrando algo que no se guardó.
      setPolicy(previo);
      setHeadroomError(
        "No se pudo guardar la optimización de contexto. El cambio se revirtió; reintentá."
      );
    }
  };

  const handleSelectCard = (id: string) => {
    if (selectedId === id) {
      setSelectedId(null);
    } else {
      setSelectedId(id);
      setTestText("");
      setTestResult(null);
      setTestError(null);
    }
  };

  const runTest = async (guardian: any) => {
    if (!testText.trim()) return;
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      const res = await api.testGuardian(guardian.id, testText);
      setTestResult(res);
    } catch (e: any) {
      setTestError(e.message || "Error al ejecutar el test.");
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center py-24 text-xs font-mono text-text-secondary">
        Cargando configuración...
      </div>
    );
  }

  const selected = guardians.find((g) => g.id === selectedId) || null;
  const isLocal = selected ? LOCAL_TYPES.has(selected.guardian_type) || selected.guardian_type === "presidio" : false;
  const isPii = selected?.guardian_type === "pii_masking";
  const isSecret = selected?.guardian_type === "secret_detection";
  const isRouting = selected?.guardian_type === "sensitive_routing";
  const isPresidio = selected?.guardian_type === "presidio";
  const isLakera = selected?.guardian_type === "lakera_prompt_injection";
  const isBedrock = selected?.guardian_type === "bedrock_guardrails";

  return (
    <div className="space-y-8 pb-16">
      {/* Header */}
      <PageHeader
        className="border-b border-border pb-5"
        title="Seguridad y Guardianes"
        subtitle="Configure guardianes de seguridad, enmascaramiento PHI/PII y optimización de contexto."
        actions={
          <Button variant="primary" onClick={handleSave} disabled={saving}>
            {saving ? "Guardando..." : "Guardar Cambios"}
          </Button>
        }
      />

      {saveSuccess && (
        <div className="bg-ok-bg border border-ok/20 text-ok px-4 py-2.5 rounded-md text-xs">
          ¡Configuración actualizada con éxito!
        </div>
      )}

      {loadError && (
        <div className="bg-danger-bg border border-danger/20 text-danger px-4 py-2.5 rounded-md text-xs">
          {loadError}
        </div>
      )}

      {estadoNoDisponible && (
        <div className="bg-warn-bg border border-warn/20 text-warn px-4 py-2.5 rounded-md text-xs">
          {estadoNoDisponible}
        </div>
      )}

      {/* ── Guardians card grid ── */}
      <div className="space-y-4">
        <div className="space-y-1">
          <h2 className={labelText}>Guardianes de Seguridad</h2>
          <p className="text-[11px] text-text-secondary">
            El estado de cada tarjeta es el estado REAL de su capa (lo que se está aplicando). El
            interruptor es el estado <span className="text-text-primary font-semibold">deseado</span>: activarlo no
            hace que la capa corra. Las capas del{" "}
            <span className="text-text-primary font-semibold">piso</span> no tienen interruptor —se aplican siempre
            y apagarlas no es configurable—, y si no se puede verificar a qué tier pertenece una capa, el
            control queda bloqueado. El detalle completo, en la sección Gobernanza.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {guardians.map((g) => {
            const local = LOCAL_TYPES.has(g.guardian_type);
            const isSelected = selectedId === g.id;
            // El borde ya no celebra el DESEO: solo se pinta de verde lo que realmente corre.
            const estado = estadoDe(g.guardian_type);
            const aplicandose = estado?.estado_efectivo === "aplicandose";
            const control = controlDeseo(g.guardian_type, !!g.is_active);

            return (
              <div
                key={g.id}
                onClick={() => handleSelectCard(g.id)}
                className={cn(
                  "border rounded-card p-4 space-y-3 cursor-pointer transition-colors",
                  isSelected
                    ? "border-primary bg-primary-tint ring-1 ring-primary/20"
                    : aplicandose
                    ? "border-ok/30 bg-ok-bg/50 hover:border-ok/50"
                    : "border-border bg-surface hover:border-border-strong"
                )}
              >
                {/* Row 1: icon + name + estado REAL */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-text-secondary text-base leading-none flex-shrink-0">
                      {GUARDIAN_ICONS[g.guardian_type] || "◈"}
                    </span>
                    <span className="font-semibold text-text-primary text-xs truncate">{g.name}</span>
                  </div>
                  <div className="flex-shrink-0">
                    {estado ? (
                      <EstadoBadge estado={estado.estado_efectivo} />
                    ) : (
                      <EstadoDesconocido
                        motivo={
                          estadoNoDisponible ||
                          "Este guardián no tiene una capa de gobernanza con correspondencia clara: no se puede afirmar que se esté aplicando."
                        }
                      />
                    )}
                  </div>
                </div>

                {/* Row 1b: DESEO (lo que el admin pidió), explícitamente separado del estado.
                    En las capas de piso NO hay deseo que expresar: el control se muestra
                    bloqueado y rotulado por lo que de verdad pasa ("Siempre activo"), nunca
                    con el "Activar: no" guardado —que es la mentira nueva que este fix mata. */}
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-text-secondary">
                    {control.esPiso ? "No configurable" : "Deseado"}
                  </span>
                  {control.habilitado ? (
                    // Toggle real del kit: cambia el DESEO local; persiste con "Guardar Cambios".
                    <span
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex flex-shrink-0"
                    >
                      <Toggle
                        size="sm"
                        checked={!!g.is_active}
                        onChange={() => handleToggleGuardian(g.id, control)}
                        label={`Activar guardián ${g.name}`}
                      />
                    </span>
                  ) : (
                    // Estados no-tocables: badge rotulado por lo que de verdad pasa.
                    <StatusBadge
                      tone={control.esPiso ? "info" : "neutral"}
                      title={control.motivo}
                      className="flex-shrink-0 text-[10px] font-bold cursor-not-allowed"
                    >
                      {control.etiqueta}
                    </StatusBadge>
                  )}
                </div>

                {/* Por qué el control está bloqueado. En texto, no solo en el `title`: un
                    interruptor gris sin explicación se lee como producto roto. */}
                {!control.habilitado && (
                  <p className="text-[10px] text-text-secondary leading-relaxed border-l-2 border-primary/20 pl-2">
                    {control.motivo}
                    {control.esPiso && !g.is_active && (
                      <span className="block mt-1 text-warn">
                        La configuración guardada figura como desactivada, pero la capa se ejecuta
                        igual: ese interruptor nunca tuvo efecto sobre el tráfico.
                      </span>
                    )}
                  </p>
                )}

                {/* Motivo del backend cuando la capa no se está aplicando (FR-013) */}
                {estado && !aplicandose && estado.motivo && (
                  <p className="text-[10px] text-text-secondary leading-relaxed border-l-2 border-border pl-2">
                    {estado.motivo}
                  </p>
                )}

                {/* Row 2: type chips */}
                <div className="flex gap-1.5 flex-wrap">
                  <span className={cn(
                    "px-1.5 py-0.5 rounded text-[10px] font-bold border",
                    local
                      ? "bg-primary-tint border-primary/20 text-primary"
                      : "bg-surface-2 border-border text-text-secondary"
                  )}>
                    {local ? "Local" : "Motor IA"}
                  </span>
                  {!local && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-2 border border-border text-text-secondary">
                      {g.apply_on || "pre_call"}
                    </span>
                  )}
                </div>

                {/* Row 3: description */}
                <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">
                  {GUARDIAN_DESCRIPTIONS[g.guardian_type] || "Guardián de seguridad configurable."}
                </p>

                {/* Row 4: configure hint */}
                <div className="flex items-center justify-between pt-0.5">
                  <span className={cn("text-[10px] transition-colors", isSelected ? "text-primary" : "text-text-secondary")}>
                    {isSelected ? "▲ Configurando" : "▼ Configurar"}
                  </span>
                  {!local && (
                    <span className="text-[10px] text-text-tertiary">Motor externo</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Config panel (below grid, for selected guardian) ── */}
        {selected && (
          <div className="border border-primary/20 rounded-card bg-primary-tint p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-sm font-bold text-text-primary">{selected.name}</span>
                <span className="ml-2 text-xs text-text-secondary">— Configuración</span>
              </div>
              <button
                onClick={() => setSelectedId(null)}
                className="text-text-secondary hover:text-text-primary text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
              >
                Cerrar ✕
              </button>
            </div>

            <div className="space-y-4 text-xs text-text-primary">
              {/* Engine: fail_mode + apply_on */}
              {!isLocal && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <label className="flex flex-col gap-1.5">
                    <span className={labelText}>Modo de fallo</span>
                    <select
                      value={selected.fail_mode || "log"}
                      onChange={(e) => handleGuardianFieldChange(selected.id, "fail_mode", e.target.value)}
                      className={controlCls}
                    >
                      <option value="block">Bloquear petición</option>
                      <option value="log">Solo registrar</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className={labelText}>Aplicar en</span>
                    <select
                      value={selected.apply_on || "pre_call"}
                      onChange={(e) => handleGuardianFieldChange(selected.id, "apply_on", e.target.value)}
                      className={controlCls}
                    >
                      <option value="pre_call">Antes del modelo (pre_call)</option>
                      <option value="post_call">Después del modelo (post_call)</option>
                      <option value="both">Ambos</option>
                    </select>
                  </label>
                </div>
              )}

              {/* Presidio (real NLP) */}
              {isPresidio && (
                <div className="space-y-4">
                  <div className="bg-surface border border-primary/20 rounded-md p-3 text-[11px] text-text-secondary space-y-1">
                    <p className="font-semibold text-text-primary">Servicios requeridos</p>
                    <p>
                      El motor NLP corre como dos microservicios HTTP independientes, incluidos en el
                      stack de despliegue (perfil del cliente). Las URLs de abajo apuntan a esos
                      servicios; los detalles de imagen y puerto viven en la guía de despliegue.
                    </p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Field
                      label="URL del analyzer NLP"
                      type="url"
                      value={selected.config.analyzer_url || ""}
                      onChange={(e) => handleGuardianConfigChange(selected.id, "analyzer_url", e.target.value)}
                      placeholder="http://<host-analyzer>:3000"
                    />
                    <Field
                      label="URL del anonymizer NLP"
                      type="url"
                      value={selected.config.anonymizer_url || ""}
                      onChange={(e) => handleGuardianConfigChange(selected.id, "anonymizer_url", e.target.value)}
                      placeholder="http://<host-anonymizer>:3001"
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <label className="flex flex-col gap-1.5">
                      <span className={labelText}>Idioma de análisis</span>
                      <select
                        value={selected.config.language || "es"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "language", e.target.value)}
                        className={controlCls}
                      >
                        <option value="es">Español</option>
                        <option value="en">English</option>
                      </select>
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className={labelText}>Acción al detectar</span>
                      <select
                        value={selected.config.action || "MASK"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "action", e.target.value)}
                        className={controlCls}
                      >
                        <option value="MASK">Anonimizar (anonymizer del motor NLP)</option>
                        <option value="BLOCK">Bloquear petición entera</option>
                      </select>
                    </label>
                  </div>
                  <div className="text-[11px] text-text-secondary bg-surface border border-border rounded-md p-3">
                    <span className="font-semibold text-text-primary">Sin URL configurada:</span>{" "}
                    el guardián <span className="text-warn">PII/PHI (regex)</span> sigue activo como fallback. El motor NLP solo toma precedencia cuando ambas URLs están configuradas.
                  </div>
                </div>
              )}

              {/* PII Masking */}
              {isPii && (
                <div className="space-y-3">
                  <label className="flex flex-col gap-1.5">
                    <span className={labelText}>Acción</span>
                    <select
                      value={selected.config.action || "MASK"}
                      onChange={(e) => handleGuardianConfigChange(selected.id, "action", e.target.value)}
                      className={controlCls}
                    >
                      <option value="MASK">Enmascarar (reemplazar con marcadores)</option>
                      <option value="BLOCK">Bloquear petición entera</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <span className={labelText}>Nombres personalizados a capturar</span>
                    <textarea
                      rows={2}
                      placeholder="Ej: Juan Pérez, María Rodríguez"
                      value={(selected.config.custom_names || []).join(", ")}
                      onChange={(e) => {
                        const list = e.target.value.split(",").map((n: string) => n.trim()).filter(Boolean);
                        handleGuardianConfigChange(selected.id, "custom_names", list);
                      }}
                      className={textareaCls}
                    />
                    <span className="text-[10px] text-text-tertiary">
                      Se enmascaran como <code>&lt;PERSON_N&gt;</code> de forma determinista.
                    </span>
                  </label>
                </div>
              )}

              {/* Secret Detection */}
              {isSecret && (
                <label className="flex flex-col gap-1.5">
                  <span className={labelText}>Acción</span>
                  <select
                    value={selected.config.action || "BLOCK"}
                    onChange={(e) => handleGuardianConfigChange(selected.id, "action", e.target.value)}
                    className={controlCls}
                  >
                    <option value="BLOCK">Bloquear (impedir envío con llaves detectadas)</option>
                    <option value="REDACT">Redactar (reemplazar con [SECRETO_REDACTADO])</option>
                  </select>
                </label>
              )}

              {/* Sensitive Routing */}
              {isRouting && (
                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Field
                      label="Modelo local (on-premise)"
                      type="text"
                      value={selected.config.on_premise_model || "ollama-llama3"}
                      onChange={(e) => handleGuardianConfigChange(selected.id, "on_premise_model", e.target.value)}
                    />
                    <label className="flex flex-col gap-1.5">
                      <span className={labelText}>Sesión persistente</span>
                      <select
                        value={selected.config.sticky_session ? "true" : "false"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "sticky_session", e.target.value === "true")}
                        className={controlCls}
                      >
                        <option value="true">Activa (toda la sesión en local)</option>
                        <option value="false">Inactiva (solo el prompt afectado)</option>
                      </select>
                    </label>
                  </div>
                  <label className="flex flex-col gap-1.5">
                    <span className={labelText}>Términos sensibles</span>
                    <textarea
                      rows={2}
                      value={(selected.config.keywords || []).join(", ")}
                      onChange={(e) => {
                        const list = e.target.value.split(",").map((k: string) => k.trim()).filter(Boolean);
                        handleGuardianConfigChange(selected.id, "keywords", list);
                      }}
                      className={textareaCls}
                    />
                  </label>
                </div>
              )}

              {/* Lakera threshold */}
              {isLakera && (
                <div className="space-y-2">
                  <label className={labelText} htmlFor="lakera-threshold">Umbral de detección</label>
                  <input
                    id="lakera-threshold"
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    value={selected.config.threshold || 0.7}
                    onChange={(e) => handleGuardianConfigChange(selected.id, "threshold", parseFloat(e.target.value))}
                    className="w-full accent-primary"
                  />
                  <div className="flex justify-between text-[10px] text-text-secondary font-mono">
                    <span>Sensible (0.1)</span>
                    <span className="text-primary font-bold">Actual: {selected.config.threshold || 0.7}</span>
                    <span>Estricto (1.0)</span>
                  </div>
                </div>
              )}

              {/* Bedrock blocked topics */}
              {isBedrock && (
                <label className="flex flex-col gap-1.5">
                  <span className={labelText}>Temas restringidos</span>
                  <textarea
                    rows={2}
                    placeholder="Ej: consejo financiero, asesoría legal no autorizada"
                    value={(selected.config.blocked_topics || []).join(", ")}
                    onChange={(e) => {
                      const list = e.target.value.split(",").map((t: string) => t.trim()).filter(Boolean);
                      handleGuardianConfigChange(selected.id, "blocked_topics", list);
                    }}
                    className={textareaCls}
                  />
                </label>
              )}

              {/* Test panel (engine-backed only) */}
              {!isLocal && (
                <div className="border-t border-border pt-4 space-y-3">
                  <label className={labelText} htmlFor="test-text">Panel de prueba</label>
                  <textarea
                    id="test-text"
                    rows={3}
                    placeholder="Ingresá texto de prueba para este guardián..."
                    value={testText}
                    onChange={(e) => setTestText(e.target.value)}
                    className={textareaCls}
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => runTest(selected)}
                    disabled={testing || !testText.trim()}
                  >
                    {testing ? "Ejecutando..." : "Ejecutar test"}
                  </Button>
                  {testError && (
                    <div className="bg-danger-bg border border-danger/20 text-danger px-3 py-2 rounded-md text-xs">{testError}</div>
                  )}
                  {testResult && (
                    <div className={cn(
                      "px-3 py-2 rounded-md text-xs border font-semibold",
                      testResult.blocked
                        ? "bg-danger-bg border-danger/20 text-danger"
                        : "bg-ok-bg border-ok/20 text-ok"
                    )}>
                      {testResult.blocked ? "BLOQUEADO" : "PERMITIDO"}
                      {testResult.reason && (
                        <span className="ml-2 font-normal text-text-secondary">{testResult.reason}</span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Headroom ── */}
      <Card>
        <div className="flex justify-between items-start gap-4">
          <div className="space-y-1">
            <h2 className={labelText}>Optimización de Contexto (Headroom)</h2>
            <p className="text-xs text-text-secondary">
              Comprime automáticamente prompts largos y código antes de enviarlos al modelo.
            </p>
          </div>
          {/* FR-008: el toggle auto-guarda al instante (optimista + revert), sin depender del
              botón "Guardar Cambios". */}
          <div className="flex items-center gap-3 shrink-0">
            <span className="text-xs font-medium text-text-secondary">
              {policy?.headroom_mode ? "Activo" : "Inactivo"}
            </span>
            <Toggle
              checked={!!policy?.headroom_mode}
              onChange={guardarHeadroom}
              disabled={!policy}
              label="Optimización de contexto (Headroom)"
            />
          </div>
        </div>

        {headroomError && (
          <div className="mt-3 bg-danger-bg border border-danger/20 text-danger px-3 py-2 rounded-md text-xs">
            {headroomError}
          </div>
        )}

        <div className="mt-4 bg-surface-2 border border-border rounded-md p-4 text-xs text-text-secondary">
          Al activar Headroom, los textos redundantes y comentarios de código se limpian localmente en la
          pasarela. Los prompts extensos se optimizan logrando ahorrar entre un 60% y 95% de tokens,
          reduciendo costos de API y acelerando la respuesta del modelo.
        </div>
      </Card>
    </div>
  );
};

export default SecurityPage;
