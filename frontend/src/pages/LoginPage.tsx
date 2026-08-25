import React, { useEffect, useState } from "react";
import { Lock, User, AlertCircle, Sparkles } from "lucide-react";
import { getBrand } from "../services/branding";
import { api } from "../services/api";
import { authStorage, SessionUser } from "../services/auth";
import { Card, Button, cn, inputBaseClass } from "../components/ui";

interface LoginPageProps {
  onLoginSuccess: (user: SessionUser) => void;
  /** Error de un intento SSO previo (pantalla de retorno del IdP que falló, `SsoCallbackPage`).
   *  Es sólo el valor inicial del banner de error: el login local lo pisa en su próximo submit,
   *  como cualquier otro error de este formulario (FR-009: el fallback nunca queda bloqueado). */
  initialError?: string;
}

/** Cuatro cuadrados de Microsoft — el asset que Microsoft documenta para botones «Sign in
 *  with Microsoft». Inline y sin red: no hay CDN de logos en esta build air-gap. */
const MicrosoftLogo: React.FC = () => (
  <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" fill="#F25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
    <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
    <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
  </svg>
);

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess, initialError }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(initialError || "");
  const [loading, setLoading] = useState(false);
  // Fail-closed por defecto (FR-010): hasta que `/available` conteste `enabled:true`, el
  // botón está AUSENTE, no deshabilitado. `getSsoAvailable` nunca lanza (colapsa cualquier
  // error a "no mostrar"), así que esto NUNCA bloquea ni retrasa el formulario local — no
  // hay spinner de carga tapando la pantalla mientras se resuelve.
  const [ssoAvailable, setSsoAvailable] = useState<{ enabled: boolean; provider_type: string | null }>({
    enabled: false,
    provider_type: null,
  });

  useEffect(() => {
    let vigente = true;
    api.getSsoAvailable().then((res) => {
      if (vigente) setSsoAvailable(res);
    });
    return () => {
      vigente = false;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.login(username, password);
      authStorage.save(res.access_token, res.user as SessionUser);
      // El user del wire trae roles del backend (p.ej. tenant_admin); el nav
      // gatea con roles normalizados — pasar SIEMPRE la sesión normalizada
      // (fix del VPS: el user crudo escondía 5 páginas hasta un refresh).
      onLoginSuccess(authStorage.getUser() as SessionUser);
    } catch (err: any) {
      setError(err.message || "Credenciales incorrectas.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4 font-sans">
      <Card noPadding className="w-full max-w-md">
        <div className="p-8">
          <div className="flex flex-col items-center text-center mb-8">
            <img
              src={getBrand().logoUrl}
              alt={getBrand().name}
              className="h-14 w-auto object-contain mb-4"
            />
            <p className="text-sm text-text-secondary">{getBrand().tagline}</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              // `role="alert"` para que un lector de pantalla anuncie el fallo del acceso sin
              // que la persona tenga que ir a buscarlo — y, de paso, es el gancho estable con
              // el que el harness E2E lee este banner (fase `motivo-idp`, #294).
              <div
                role="alert"
                className="bg-danger-bg text-danger px-4 py-3 rounded-md flex items-center gap-3 text-sm"
              >
                <AlertCircle className="w-5 h-5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                Usuario
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none text-text-tertiary">
                  <User className="w-4 h-4" />
                </span>
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="admin"
                  className={cn(inputBaseClass, "h-11 pl-10 border-border")}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                Contraseña
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none text-text-tertiary">
                  <Lock className="w-4 h-4" />
                </span>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className={cn(inputBaseClass, "h-11 pl-10 border-border")}
                />
              </div>
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              disabled={loading}
              className="w-full"
              leftIcon={
                loading ? (
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Sparkles className="w-5 h-5" />
                )
              }
            >
              {loading ? "Ingresando..." : "Ingresar al Panel"}
            </Button>
          </form>

          {/* Ausente por defecto (FR-010): sólo se monta cuando `/available` confirmó
              `enabled:true`. No es un botón deshabilitado ni con tooltip — la superficie
              directamente no existe hasta que el backend la confirma. */}
          {ssoAvailable.enabled && (
            <div className="mt-5 pt-5 border-t border-border">
              <Button
                type="button"
                variant="secondary"
                size="lg"
                className="w-full"
                onClick={() => api.startSsoLogin()}
                leftIcon={<MicrosoftLogo />}
              >
                Entrar con Microsoft
              </Button>
            </div>
          )}

          <div className="mt-8 pt-6 border-t border-border text-center">
            <p className="text-xs text-text-tertiary">
              Acceso seguro encriptado y auditado por la pasarela de cumplimiento.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
};
