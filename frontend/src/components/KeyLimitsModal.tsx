import React, { useState } from "react";
import { Button, Card, Field } from "./ui";

export interface KeyLimits {
  rpm_limit?: number;
  tpm_limit?: number;
}

// Mismos rangos que el alta de la llave (UsersPage): el servidor solo exige ≥ 1, pero un tope tipeado de más
// casi siempre es un error de dedo y apagaría la protección.
const RPM_RANGE = { min: 1, max: 10000 };
const TPM_RANGE = { min: 1000, max: 10000000 };

const enRango = (v: number, r: { min: number; max: number }) => Number.isInteger(v) && v >= r.min && v <= r.max;

interface Props {
  keyName: string;
  rpm: number;
  tpm: number;
  /** Recibe solo lo que cambió. Si rechaza, el mensaje del error se muestra y el modal sigue abierto. */
  onSave: (limits: KeyLimits) => Promise<void>;
  onClose: () => void;
}

/** Edición de los límites rpm/tpm de una llave existente (057): el servidor los aplica en la pasarela y en el motor. */
export const KeyLimitsModal: React.FC<Props> = ({ keyName, rpm, tpm, onSave, onClose }) => {
  const [rpmValue, setRpmValue] = useState(String(rpm));
  const [tpmValue, setTpmValue] = useState(String(tpm));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const nextRpm = Number(rpmValue);
  const nextTpm = Number(tpmValue);
  const changed = nextRpm !== rpm || nextTpm !== tpm;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enRango(nextRpm, RPM_RANGE)) {
      setError(`El límite RPM debe ser un entero entre ${RPM_RANGE.min} y ${RPM_RANGE.max.toLocaleString("es-AR")}.`);
      return;
    }
    if (!enRango(nextTpm, TPM_RANGE)) {
      setError(`El límite TPM debe ser un entero entre ${TPM_RANGE.min.toLocaleString("es-AR")} y ${TPM_RANGE.max.toLocaleString("es-AR")}.`);
      return;
    }
    const limits: KeyLimits = {};
    if (nextRpm !== rpm) limits.rpm_limit = nextRpm;
    if (nextTpm !== tpm) limits.tpm_limit = nextTpm;
    setError(null);
    setSaving(true);
    try {
      await onSave(limits);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron guardar los límites.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md">
        <Card title="Editar límites de la llave">
          <form onSubmit={submit} noValidate className="space-y-4 text-xs">
            <p className="text-text-secondary">
              Llave <span className="font-semibold text-text-primary">{keyName}</span>. El cambio rige de inmediato en la
              pasarela y en el motor.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <Field
                label={<>Límite RPM <span className="text-text-tertiary normal-case">(solicitudes/min)</span></>}
                type="number"
                min={RPM_RANGE.min}
                max={RPM_RANGE.max}
                value={rpmValue}
                onChange={(e) => setRpmValue(e.target.value)}
              />
              <Field
                label={<>Límite TPM <span className="text-text-tertiary normal-case">(tokens/min)</span></>}
                type="number"
                min={TPM_RANGE.min}
                max={TPM_RANGE.max}
                value={tpmValue}
                onChange={(e) => setTpmValue(e.target.value)}
              />
            </div>
            {error && <p role="alert" className="text-danger">{error}</p>}
            <div className="flex justify-end gap-3 pt-4 border-t border-border">
              <Button type="button" variant="secondary" size="sm" onClick={onClose}>Cancelar</Button>
              <Button type="submit" variant="primary" size="sm" disabled={saving || !changed}>
                {saving ? "Guardando..." : "Guardar"}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
};
