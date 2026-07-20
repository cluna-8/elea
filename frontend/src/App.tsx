import React, { useState } from "react";
import { getBrand } from "./services/branding";
import { UsersPage } from "./pages/UsersPage";
import { SecurityPage } from "./pages/SecurityPage";
import { CompliancePage } from "./pages/CompliancePage";
import { DocsPage } from "./pages/DocsPage";
import { AuditPage } from "./pages/AuditPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { ModelsPage } from "./pages/ModelsPage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { CostsPage } from "./pages/CostsPage";
import { authStorage, SessionUser, ROLE_LABELS, ROLE_PERMISSIONS } from "./services/auth";

type Page = "dashboard" | "playground" | "users" | "security" | "compliance" | "audit" | "models" | "costs" | "docs";

export const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<Page>("dashboard");
  const [currentUser, setCurrentUser] = useState<SessionUser | null>(authStorage.getUser());

  const navigation = [
    { id: "dashboard", name: "Panel Principal", roles: null },
    { id: "playground", name: "Playground", roles: null },
    { id: "models", name: "Modelos & Ollama", roles: null },
    { id: "costs", name: "Costos", roles: ["admin", "compliance_officer"] },
    { id: "users", name: "Usuarios & Presupuestos", roles: ["admin"] },
    { id: "security", name: "Seguridad y Guardianes", roles: ["admin", "compliance_officer"] },
    { id: "compliance", name: "Políticas de Cumplimiento", roles: ["admin", "compliance_officer"] },
    { id: "audit", name: "Logs de Auditoría", roles: ["admin", "compliance_officer"] },
    { id: "docs", name: "Documentación", roles: null },
  ];

  const handleLogin = (user: SessionUser) => {
    setCurrentUser(user);
    setCurrentPage("dashboard");
  };

  const handleLogout = () => {
    authStorage.clear();
    setCurrentUser(null);
  };

  if (!currentUser) {
    return <LoginPage onLoginSuccess={handleLogin} />;
  }

  const visibleNav = navigation.filter(item =>
    !item.roles || item.roles.includes(currentUser.role)
  );

  return (
    <div className="flex h-screen bg-background overflow-hidden font-sans">
      {/* Sidebar Navigation */}
      <aside className="w-64 bg-panel border-r border-slate-700/50 flex flex-col justify-between shrink-0">
        <div className="flex flex-col flex-1">
          {/* Logo / Branding */}
          <div className="p-5 border-b border-slate-700/50">
            <img src={getBrand().logoUrl} alt={getBrand().name} className="h-10 w-auto object-contain" />
          </div>

          {/* Navigation Links */}
          <nav className="flex-1 px-4 py-6 space-y-1">
            {visibleNav.map((item) => {
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

        {/* Current User & Logout */}
        <div className="p-4 border-t border-slate-700/50 space-y-3">
          <div className="flex items-center justify-between bg-background/40 p-2.5 rounded-xl border border-slate-700/30">
            <div className="text-left overflow-hidden">
              <p className="text-xs font-bold text-white leading-none truncate">{currentUser.username}</p>
              <span className="text-[9px] text-primary font-mono">{ROLE_LABELS[currentUser.role] || currentUser.role}</span>
            </div>
            <button
              onClick={handleLogout}
              className="text-xs text-text-secondary hover:text-danger font-semibold transition-all shrink-0 ml-2"
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
        {currentPage === "costs" && <CostsPage />}
        {currentPage === "users" && <UsersPage />}
        {currentPage === "security" && <SecurityPage />}
        {currentPage === "compliance" && <CompliancePage />}
        {currentPage === "audit" && <AuditPage />}
        {currentPage === "docs" && <DocsPage />}
      </main>
    </div>
  );
};
export default App;
