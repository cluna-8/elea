import React, { useState } from "react";
import { Shield, Lock, User, AlertCircle, Sparkles } from "lucide-react";

interface LoginPageProps {
  onLoginSuccess: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    // Simulate small delay for premium UX feel
    setTimeout(() => {
      if (username === "admin" && password === "admin") {
        localStorage.setItem("basa_admin_logged", "true");
        onLoginSuccess();
      } else {
        setError("Credenciales incorrectas. Pruebe con admin / admin.");
        setLoading(false);
      }
    }, 800);
  };

  return (
    <div className="min-h-screen bg-background flex flex-col justify-center items-center p-4 relative overflow-hidden">
      {/* Dynamic glow background elements */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl -z-10 animate-pulse" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-success/5 rounded-full blur-3xl -z-10" />

      <div className="w-full max-w-md bg-panel border border-slate-700/50 rounded-2xl p-8 shadow-2xl backdrop-blur-md relative">
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center border border-primary/20 mb-4">
            <Shield className="w-8 h-8 text-primary animate-pulse" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-wide">BASA Secure AI Gateway</h1>
          <p className="text-sm text-text-secondary mt-1">by basa dev</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-3 rounded-lg flex items-center gap-3 text-sm">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Usuario</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 pointer-events-none text-text-secondary">
                <User className="w-5 h-5" />
              </span>
              <input
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                className="w-full bg-background border border-slate-700/60 rounded-xl pl-11 pr-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Contraseña</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 pointer-events-none text-text-secondary">
                <Lock className="w-5 h-5" />
              </span>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-background border border-slate-700/60 rounded-xl pl-11 pr-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-primary hover:bg-primary/95 text-background font-bold py-3.5 px-4 rounded-xl transition-all shadow-lg hover:shadow-primary/10 flex items-center justify-center gap-2"
          >
            {loading ? (
              <span className="w-5 h-5 border-2 border-background border-t-transparent rounded-full animate-spin" />
            ) : (
              <>
                <Sparkles className="w-5 h-5" />
                <span>Ingresar al Panel</span>
              </>
            )}
          </button>
        </form>

        <div className="mt-8 pt-6 border-t border-slate-700/30 text-center">
          <p className="text-xs text-text-secondary">
            Acceso seguro encriptado y auditado por la pasarela de cumplimiento.
          </p>
          <p className="text-[10px] text-primary/60 mt-1.5">
            Demo credentials: admin / admin
          </p>
        </div>
      </div>
    </div>
  );
};
