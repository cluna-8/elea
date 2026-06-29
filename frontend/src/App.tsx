import React, { useState } from "react";
import { UsersPage } from "./pages/UsersPage";
import { SecurityPage } from "./pages/SecurityPage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { AuditPage } from "./pages/AuditPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { ModelsPage } from "./pages/ModelsPage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";

type Page = "dashboard" | "playground" | "users" | "security" | "policies" | "audit" | "models";

export const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<Page>("dashboard");
  const [isLogged, setIsLogged] = useState<boolean>(!!localStorage.getItem("basa_admin_logged"));

  const navigation = [
    { id: "dashboard", name: "Panel Principal" },
    { id: "playground", name: "Playground" },
    { id: "models", name: "Modelos & Ollama" },
    { id: "users", name: "Usuarios & Presupuestos" },
    { id: "security", name: "Seguridad y Guardianes" },
    { id: "policies", name: "Políticas de Cumplimiento" },
    { id: "audit", name: "Logs de Auditoría" },
  ];

  const handleLogout = () => {
    localStorage.removeItem("basa_admin_logged");
    setIsLogged(false);
  };

  if (!isLogged) {
    return <LoginPage onLoginSuccess={() => setIsLogged(true)} />;
  }

  return (
    <div className="flex h-screen bg-background overflow-hidden font-sans">
      {/* Sidebar Navigation */}
      <aside className="w-64 bg-panel border-r border-slate-700/50 flex flex-col justify-between shrink-0">
        <div className="flex flex-col flex-1">
          {/* Logo / Branding (White label - by basa dev) */}
          <div className="p-6 border-b border-slate-700/50">
            <div>
              <h1 className="font-bold text-white tracking-tight leading-none text-md">
                Basa Secure AI Gateway
              </h1>
              <span className="text-[10px] text-primary font-semibold tracking-wider uppercase font-mono mt-1.5 block">
                by basa dev
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="flex-1 px-4 py-6 space-y-1">
            {navigation.map((item) => {
              const isActive = currentPage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setCurrentPage(item.id as Page)}
                  className={`w-full text-left px-4 py-3 rounded-lg text-sm font-medium transition-all focus:outline-none focus:ring-2 focus:ring-primary ${
                    isActive
                      ? "bg-primary text-background font-semibold"
                      : "text-text-secondary hover:text-white hover:bg-slate-800/40"
                  }`}
                >
                  {item.name}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Logged in Admin Profile & Logout */}
        <div className="p-4 border-t border-slate-700/50 space-y-3">
          <div className="flex items-center justify-between bg-background/40 p-2.5 rounded-xl border border-slate-700/30">
            <div className="text-left">
              <p className="text-xs font-bold text-white leading-none">Admin BASA</p>
              <span className="text-[9px] text-text-secondary font-mono">Super Admin</span>
            </div>
            <button
              onClick={handleLogout}
              className="text-xs text-text-secondary hover:text-danger font-semibold transition-all"
            >
              Salir
            </button>
          </div>
          <div className="text-center">
            <span className="text-[10px] text-text-secondary font-mono">
              V1.0.0 | Entorno Seguro
            </span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto bg-background p-6">
        {currentPage === "dashboard" && <DashboardPage />}
        {currentPage === "playground" && <PlaygroundPage />}
        {currentPage === "models" && <ModelsPage />}
        {currentPage === "users" && <UsersPage />}
        {currentPage === "security" && <SecurityPage />}
        {currentPage === "policies" && <PoliciesPage />}
        {currentPage === "audit" && <AuditPage />}
      </main>
    </div>
  );
};
export default App;
