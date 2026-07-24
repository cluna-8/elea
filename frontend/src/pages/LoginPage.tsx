import React, { useState } from "react";
import { Lock, User, AlertCircle, Sparkles } from "lucide-react";
import { getBrand } from "../services/branding";
import { api } from "../services/api";
import { authStorage, SessionUser } from "../services/auth";
import { Card, Button, cn, inputBaseClass } from "../components/ui";

interface LoginPageProps {
  onLoginSuccess: (user: SessionUser) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
              <div className="bg-danger-bg text-danger px-4 py-3 rounded-md flex items-center gap-3 text-sm">
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
