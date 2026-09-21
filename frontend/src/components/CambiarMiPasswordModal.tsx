import React, { useState } from "react";
import { api, MIN_PASSWORD_LEN, validarPassword } from "../services/api";
import { Card, Button, PasswordField, cn } from "./ui";

/** Cambio de la PROPIA contraseña, para cualquier rol autenticado.
 *
 *  Vive fuera de la página de Usuarios (que es admin-only) porque si el único camino para
 *  rotar una credencial es el reseteo del administrador, con 125 personas quedan 125
 *  contraseñas que alguien más tecleó, vio y comunicó por WhatsApp — y que su dueño no puede
 *  cambiar. La política de longitud sólo es sostenible si el dueño de la cuenta puede rotarla.
 *
 *  El error se muestra DENTRO del modal: el 401 de este endpoint significa "la contraseña
 *  actual no coincide", no sesión vencida, así que echar a la persona por un tipeo le haría
 *  perder el formulario y parecería un fallo del producto (`api.changeOwnPassword` ya no
 *  trata ese 401 como sesión vencida). */
export const CambiarMiPasswordModal: React.FC<{
  onClose: () => void;
  /** Contraseña fijada por un admin: no hay forma de cerrar sin cambiarla primero. */
  obligatorio?: boolean;
}> = ({ onClose, obligatorio = false }) => {
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [errorNueva, setErrorNueva] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [listo, setListo] = useState(false);

  const enviar = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const invalida = validarPassword(nueva);
    if (invalida) {
      setErrorNueva(invalida);
      return;
    }
    // La repetición se compara acá y no en el servidor: el backend recibe una sola
    // contraseña, y un tipeo en una credencial que nadie más conoce deja a la persona
    // afuera de su propia cuenta.
    if (nueva !== repetida) {
      setErrorNueva("Las dos contraseñas nuevas no coinciden.");
      return;
    }
    setErrorNueva(null);
    setEnviando(true);
    try {
      await api.changeOwnPassword(actual, nueva);
      setListo(true);
      setActual(""); setNueva(""); setRepetida("");
    } catch (err: any) {
      setError(err?.message || "No se pudo cambiar la contraseña.");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className={cn("w-full", "max-w-md")}>
        <Card title={obligatorio ? "Debe cambiar su contraseña para continuar" : "Cambiar mi contraseña"}>
          {listo ? (
            <div className="space-y-4">
              <div className="bg-ok-bg border border-ok/20 text-ok px-4 py-2.5 rounded-md text-xs">
                Contraseña actualizada. La próxima vez que inicie sesión, use la nueva.
              </div>
              <div className="flex justify-end">
                <Button type="button" onClick={onClose}>Cerrar</Button>
              </div>
            </div>
          ) : (
            <form onSubmit={enviar} className="space-y-4">
              {obligatorio && (
                <div className="bg-canvas border border-border text-text-secondary px-4 py-2.5 rounded-md text-xs">
                  Su contraseña fue definida por un administrador. Debe cambiarla antes de
                  continuar.
                </div>
              )}
              {error && (
                <div className="bg-danger-bg border border-danger/20 text-danger px-4 py-2.5 rounded-md text-xs">
                  {error}
                </div>
              )}
              <PasswordField
                id="mi-password-actual"
                label="Contraseña actual"
                value={actual}
                onChange={(v) => { setActual(v); if (error) setError(null); }}
                autoComplete="current-password"
                placeholder="La que usa hoy"
              />
              <PasswordField
                id="mi-password-nueva"
                label="Contraseña nueva"
                value={nueva}
                onChange={(v) => { setNueva(v); if (errorNueva) setErrorNueva(null); }}
                error={errorNueva}
                placeholder={`Mínimo ${MIN_PASSWORD_LEN} caracteres`}
                hint={`Mínimo ${MIN_PASSWORD_LEN} caracteres. Nadie más tiene por qué conocerla.`}
              />
              <PasswordField
                id="mi-password-repetida"
                label="Repetir la nueva"
                value={repetida}
                onChange={(v) => { setRepetida(v); if (errorNueva) setErrorNueva(null); }}
                placeholder="Escríbala otra vez"
              />
              <div className="flex justify-end gap-3 pt-4 border-t border-border">
                {!obligatorio && (
                  <Button type="button" variant="secondary" onClick={onClose} disabled={enviando}>
                    Cancelar
                  </Button>
                )}
                <Button type="submit" disabled={enviando}>
                  {enviando ? "Guardando…" : "Cambiar contraseña"}
                </Button>
              </div>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
};
