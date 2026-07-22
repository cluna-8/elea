import React, { useState, useEffect } from "react";
import { api, SecurityPolicy } from "../services/api";

export const PoliciesPage: React.FC = () => {
  const [policies, setPolicies] = useState<SecurityPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<SecurityPolicy | null>(null);
  
  // Form State
  const [name, setName] = useState("");
  const [isActive, setIsActive] = useState(false);
  const [gdprMode, setGdprMode] = useState(false);
  const [aiActMode, setAiActMode] = useState(false);
  const [headroomMode, setHeadroomMode] = useState(false);
  // El tipo se estrecha al vocabulario real de acciones (el `select` de abajo solo produce
  // esos tres valores): con `Record<string, string>` el objeto no encajaba en `SecurityPolicy`
  // y el guardado no compilaba — invisible mientras el build no chequeó tipos.
  const [entities, setEntities] = useState<Record<string, "MASK" | "BLOCK" | "ALLOW">>({
    PERSON: "MASK",
    DNI: "MASK",
    CUIL: "MASK",
    PHONE_NUMBER: "MASK",
    EMAIL_ADDRESS: "MASK",
    MEDICAL_LICENSE: "BLOCK"
  });

  const fetchPolicies = async () => {
    try {
      const data = await api.getPolicies();
      setPolicies(data);
    } catch (err) {
      console.error("Error fetching policies:", err);
      setError("Error al cargar la lista de políticas de seguridad.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPolicies();
  }, []);

  const handleOpenCreate = () => {
    setEditingPolicy(null);
    setName("");
    setIsActive(false);
    setGdprMode(false);
    setAiActMode(false);
    setHeadroomMode(false);
    setEntities({
      PERSON: "MASK",
      DNI: "MASK",
      CUIL: "MASK",
      PHONE_NUMBER: "MASK",
      EMAIL_ADDRESS: "MASK",
      MEDICAL_LICENSE: "BLOCK"
    });
    setIsModalOpen(true);
  };

  const handleOpenEdit = (policy: SecurityPolicy) => {
    setEditingPolicy(policy);
    setName(policy.name);
    setIsActive(policy.is_active);
    setGdprMode(policy.gdpr_mode);
    setAiActMode(policy.ai_act_mode);
    setHeadroomMode(policy.headroom_mode);
    // El default de una entidad sin configurar era `"OFF"`, un valor que NO existe: ni está
    // en el `select` (ALLOW/MASK/BLOCK) ni en el vocabulario que acepta el backend. Al editar
    // una política con alguna entidad ausente, el desplegable quedaba sin opción coincidente
    // y al guardar se enviaba "OFF". `ALLOW` es el equivalente honesto —entidad no
    // configurada = no se enmascara— y sí es un valor válido en ambos lados.
    setEntities({
      PERSON: policy.entity_configs.PERSON || "ALLOW",
      DNI: policy.entity_configs.DNI || "ALLOW",
      CUIL: policy.entity_configs.CUIL || "ALLOW",
      PHONE_NUMBER: policy.entity_configs.PHONE_NUMBER || "ALLOW",
      EMAIL_ADDRESS: policy.entity_configs.EMAIL_ADDRESS || "ALLOW",
      MEDICAL_LICENSE: policy.entity_configs.MEDICAL_LICENSE || "ALLOW"
    });
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setActionLoading(true);
    setError("");
    setSuccess("");

    const policyData = {
      name,
      is_active: isActive,
      gdpr_mode: gdprMode,
      ai_act_mode: aiActMode,
      headroom_mode: headroomMode,
      entity_configs: entities
    };

    try {
      if (editingPolicy) {
        // `api.updatePolicy` no existe: el método es `updatePolicyById`. Era un TypeError en
        // cada edición, que el `catch` de abajo convertía en "Error al guardar la política" —
        // o sea editar una política de cumplimiento fallaba SIEMPRE y parecía un error del
        // servidor. Sin chequeo de tipos en el build, nadie lo vio.
        await api.updatePolicyById(editingPolicy.id, policyData);
        setSuccess("Política actualizada con éxito.");
      } else {
        await api.createPolicy(policyData);
        setSuccess("Política de cumplimiento creada con éxito.");
      }
      setIsModalOpen(false);
      await fetchPolicies();
    } catch (err: any) {
      setError(err.message || "Error al guardar la política de seguridad.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`¿Está seguro de que desea eliminar la política "${name}"?`)) return;

    setActionLoading(true);
    setError("");
    setSuccess("");

    try {
      await api.deletePolicy(id);
      setSuccess("Política eliminada con éxito.");
      await fetchPolicies();
    } catch (err: any) {
      setError(err.message || "Error al eliminar la política.");
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold text-white">Políticas de Cumplimiento</h1>
          <p className="text-xs text-text-secondary mt-1">
            Defina perfiles de cumplimiento normativo específicos para diferentes casos de uso médicos o regulatorios.
          </p>
        </div>
        <button
          onClick={handleOpenCreate}
          className="bg-primary hover:bg-primary/95 text-background font-bold px-4 py-2 rounded text-xs transition-all"
        >
          Crear Política
        </button>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-2.5 rounded-lg text-xs">
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">
          <span>{success}</span>
        </div>
      )}

      {/* Policies List Card */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary mb-4">
          Perfiles de Políticas Registrados
        </h2>

        {loading ? (
          <div className="py-12 text-center text-xs font-mono text-text-secondary">
            Cargando políticas...
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {policies.map((p) => (
              <div key={p.id} className="border border-slate-700/40 bg-background/15 rounded p-4 space-y-4 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <h3 className="text-sm font-bold text-white">{p.name}</h3>
                    {p.is_active ? (
                      <span className="text-[10px] bg-success/10 text-success border border-success/20 px-2 py-0.5 rounded font-mono">
                        Activa
                      </span>
                    ) : (
                      <span className="text-[10px] bg-slate-800 text-text-secondary border border-slate-700 px-2 py-0.5 rounded font-mono">
                        Inactiva
                      </span>
                    )}
                  </div>
                  <div className="space-y-1 text-xs text-text-secondary">
                    <div>GDPR (Residencia UE): <span className="text-white">{p.gdpr_mode ? "Activo" : "Inactivo"}</span></div>
                    <div>AI Act (UE): <span className="text-white">{p.ai_act_mode ? "Activo" : "Inactivo"}</span></div>
                    <div>Headroom (Compresión): <span className="text-white">{p.headroom_mode ? "Activo" : "Inactivo"}</span></div>
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-slate-750">
                  <button
                    onClick={() => handleOpenEdit(p)}
                    className="text-xs text-text-secondary hover:text-white font-semibold transition-all px-2 py-1"
                  >
                    Editar
                  </button>
                  <button
                    onClick={() => handleDelete(p.id, p.name)}
                    disabled={p.is_active || actionLoading}
                    className="text-xs text-danger hover:text-danger/80 font-semibold transition-all px-2 py-1 disabled:opacity-30"
                  >
                    Eliminar
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Policy Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-lg w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-base font-bold">{editingPolicy ? "Editar Política" : "Crear Nueva Política"}</h3>
            <form onSubmit={handleSave} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Nombre de la Política</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="ej: Producción Médica Estricta"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                />
              </div>

              <div className="space-y-2">
                <label className="text-text-secondary font-medium block">Opciones del Perfil</label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isActive}
                      onChange={(e) => setIsActive(e.target.checked)}
                      className="accent-primary"
                    />
                    Establecer como Activa
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={gdprMode}
                      onChange={(e) => setGdprMode(e.target.checked)}
                      className="accent-primary"
                    />
                    Forzar Residencia GDPR (UE)
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={aiActMode}
                      onChange={(e) => setAiActMode(e.target.checked)}
                      className="accent-primary"
                    />
                    Filtros AI Act de la UE
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={headroomMode}
                      onChange={(e) => setHeadroomMode(e.target.checked)}
                      className="accent-primary"
                    />
                    Activar Headroom por Defecto
                  </label>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-text-secondary font-medium block">Configuración de Enmascaramiento de Entidades</label>
                <div className="grid grid-cols-2 gap-3 max-h-40 overflow-y-auto pr-1 border border-slate-700/40 p-2.5 rounded bg-background/30">
                  {Object.keys(entities).map((entity) => (
                    <div key={entity} className="flex justify-between items-center gap-2">
                      <span className="text-[10px] font-mono text-text-secondary">{entity}</span>
                      <select
                        value={entities[entity]}
                        onChange={(e) =>
                          setEntities({ ...entities, [entity]: e.target.value as "MASK" | "BLOCK" | "ALLOW" })
                        }
                        className="bg-background border border-slate-700 rounded p-1 text-[10px]"
                      >
                        <option value="ALLOW">Permitir</option>
                        <option value="MASK">Enmascarar</option>
                        <option value="BLOCK">Bloquear</option>
                      </select>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-750">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 rounded bg-slate-850 hover:bg-slate-800 text-white"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all"
                >
                  {actionLoading ? "Guardando..." : "Guardar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
export default PoliciesPage;
