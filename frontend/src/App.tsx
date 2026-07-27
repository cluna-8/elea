import React, { useState } from "react";
import { LayoutDashboard, FlaskConical, Activity, Boxes, Wallet, Users as UsersIcon, Scale, ShieldCheck, ClipboardCheck, ScrollText, BookOpen } from "lucide-react";
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
import { UserPortal } from "./pages/UserPortal";
import { CostsPage } from "./pages/CostsPage";
import { FirewallMonitorPage } from "./pages/FirewallMonitorPage";
import { GovernancePage } from "./pages/GovernancePage";
import { CambiarMiPasswordModal } from "./components/CambiarMiPasswordModal";
// `ROLE_PERMISSIONS` se importaba y no se usaba desde antes de esta rama: el gating del nav
// se resuelve con el campo `roles` de cada item (más abajo). Se saca el import muerto en vez
// de silenciarlo — dejarlo sugería un mecanismo de permisos que este archivo no aplica.
import { authStorage, SessionUser, ROLE_LABELS } from "./services/auth";

// Agregar una sección son TRES ediciones sincronizadas en este archivo: este union, el item
// de `navigation` y el render condicional de abajo. Si falta una, el usuario hace click y
// ve una pantalla en blanco sin ningún error.
type Page = "dashboard" | "playground" | "firewall" | "users" | "governance" | "security" | "compliance" | "audit" | "models" | "costs" | "docs";

export const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<Page>("dashboard");
  const [currentUser, setCurrentUser] = useState<SessionUser | null>(authStorage.getUser());
  // El cambio de la propia contraseña vive acá y no en una página del nav: es de CUALQUIER
  // rol, y la única pantalla con campos de contraseña (Usuarios) es admin-only. Sin esto, la
  // credencial que reparte el administrador al dar de alta a alguien no la puede rotar su
  // propio dueño.
  const [cambiarPassword, setCambiarPassword] = useState(false);

  const navigation = [
    { id: "dashboard", name: "Panel Principal", icon: LayoutDashboard, roles: null },
    { id: "playground", name: "Playground", icon: FlaskConical, roles: null },
    { id: "firewall", name: "Firewall en vivo", icon: Activity, roles: ["admin", "compliance_officer"] },
    { id: "models", name: "Modelos & Ollama", icon: Boxes, roles: null },
    { id: "costs", name: "Costos", icon: Wallet, roles: ["admin", "compliance_officer"] },
    { id: "users", name: "Usuarios & Presupuestos", icon: UsersIcon, roles: ["admin"] },
    // OJO: este array usa el vocabulario LEGACY de roles — `visibleNav` compara contra el
    // rol ya normalizado por `toLegacyRole` (services/auth.ts), que colapsa tenant_admin y
    // super_admin en "admin". Escribir "tenant_admin" acá hace que el item no se muestre
    // NUNCA, y falla en silencio. El gate real es admin-only en el router del backend.
    { id: "governance", name: "Gobernanza", icon: Scale, roles: ["admin"] },
    { id: "security", name: "Seguridad y Guardianes", icon: ShieldCheck, roles: ["admin", "compliance_officer"] },
    { id: "compliance", name: "Políticas de Cumplimiento", icon: ClipboardCheck, roles: ["admin", "compliance_officer"] },
    { id: "audit", name: "Logs de Auditoría", icon: ScrollText, roles: ["admin", "compliance_officer"] },
    { id: "docs", name: "Documentación", icon: BookOpen, roles: null },
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

  // Usuario final → portal, JAMÁS la consola de administración. El login devuelve el rol
  // canónico post-013 ("client", users.py) y authStorage lo guarda pasado por toLegacyRole
  // (services/auth.ts), que deja "client" tal cual salvo cuando display_label es
  // "clinician"/"developer". Por eso el gate cubre "client" y "clinician" (el usuario final
  // histórico); "developer" conserva la consola, igual que en el predecesor.
  if (currentUser.role === "client" || currentUser.role === "clinician") {
    return <UserPortal user={currentUser} onLogout={handleLogout} />;
  }

  const visibleNav = navigation.filter(item =>
    !item.roles || item.roles.includes(currentUser.role)
  );

  return (
    <div className="flex h-screen bg-canvas overflow-hidden font-sans">
      {/* Sidebar Navigation */}
      <aside className="w-64 bg-surface border-r border-border flex flex-col justify-between shrink-0">
        <div className="flex flex-col flex-1 min-h-0">
          {/* Logo / Branding */}
          <div className="p-5 border-b border-border">
            <img src={getBrand().logoUrl} alt={getBrand().name} className="h-10 w-auto object-contain" />
          </div>

          {/* Navigation Links */}
          <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-0.5">
            {visibleNav.map((item) => {
              const isActive = currentPage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setCurrentPage(item.id as Page)}
                  aria-current={isActive ? "page" : undefined}
                  className={`w-full flex items-center gap-2.5 text-left px-4 py-2.5 rounded-r-md border-l-2 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset ${
                    isActive
                      ? "border-primary bg-primary-tint text-primary font-semibold"
                      : "border-transparent text-text-secondary hover:text-text-primary hover:bg-surface-2 font-medium"
                  }`}
                >
                  <item.icon className="w-4 h-4 shrink-0" aria-hidden="true" />
                  <span className="truncate">{item.name}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Current User & Logout */}
        <div className="p-4 border-t border-border space-y-3">
          <div className="flex items-center justify-between bg-surface-2 p-2.5 rounded-md border border-border">
            <div className="text-left overflow-hidden">
              <p className="text-xs font-bold text-text-primary leading-none truncate">{currentUser.username}</p>
              <span className="text-[9px] text-primary font-mono">{ROLE_LABELS[currentUser.role] || currentUser.role}</span>
            </div>
            <button
              onClick={handleLogout}
              className="text-xs text-text-secondary hover:text-danger font-semibold transition-colors shrink-0 ml-2"
            >
              Salir
            </button>
          </div>
          <button
            onClick={() => setCambiarPassword(true)}
            className="w-full text-left text-[11px] text-text-secondary hover:text-primary font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
          >
            Cambiar mi contraseña
          </button>
          <div className="text-center">
            <span className="text-[10px] text-text-tertiary font-mono">
              V1.0.0 | Entorno Seguro
            </span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto bg-canvas p-6">
        {currentPage === "dashboard" && <DashboardPage />}
        {currentPage === "playground" && <PlaygroundPage />}
        {currentPage === "firewall" && <FirewallMonitorPage />}
        {currentPage === "models" && <ModelsPage />}
        {currentPage === "costs" && <CostsPage />}
        {currentPage === "users" && <UsersPage />}
        {currentPage === "governance" && <GovernancePage />}
        {currentPage === "security" && <SecurityPage />}
        {currentPage === "compliance" && <CompliancePage />}
        {currentPage === "audit" && <AuditPage />}
        {currentPage === "docs" && <DocsPage />}
      </main>

      {cambiarPassword && <CambiarMiPasswordModal onClose={() => setCambiarPassword(false)} />}
    </div>
  );
};
export default App;
