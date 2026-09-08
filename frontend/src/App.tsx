import React, { useState } from "react";
import { LayoutDashboard, FlaskConical, Activity, Boxes, Wallet, Users as UsersIcon, Scale, ShieldCheck, ClipboardCheck, ScrollText, BookOpen, FolderOpen } from "lucide-react";
import { getBrand } from "./services/branding";
import { UsersPage } from "./pages/UsersPage";
import { WorkspacesUnassignedPage } from "./pages/WorkspacesUnassignedPage";
import { SecurityPage } from "./pages/SecurityPage";
import { CompliancePage } from "./pages/CompliancePage";
import { DocsPage } from "./pages/DocsPage";
import { AuditPage } from "./pages/AuditPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { ModelsPage } from "./pages/ModelsPage";
import { LoginPage } from "./pages/LoginPage";
import { SsoCallbackPage } from "./pages/SsoCallbackPage";
import { DashboardPage } from "./pages/DashboardPage";
import { UserPortal } from "./pages/UserPortal";
import { CostsPage } from "./pages/CostsPage";
import { FirewallMonitorPage } from "./pages/FirewallMonitorPage";
import { GovernancePage } from "./pages/GovernancePage";
import { CambiarMiPasswordModal } from "./components/CambiarMiPasswordModal";
import { authStorage, SessionUser, ROLE_LABELS } from "./services/auth";
// El gating del nav DERIVA de la matriz canónica (`roleMatrix.ts`, espejo del contrato), no de
// una tabla de roles hardcodeada que vuelva a driftear (Regla 5 aplicada al front): cada item
// declara el GRUPO DE SUPERFICIE que representa y se muestra si el rol puede VERLO (`canView`).
import { canView, SurfaceGroup } from "./services/roleMatrix";

// Agregar una sección son TRES ediciones sincronizadas en este archivo: este union, el item
// de `navigation` y el render condicional de abajo. Si falta una, el usuario hace click y
// ve una pantalla en blanco sin ningún error.
type Page = "dashboard" | "playground" | "firewall" | "users" | "workspaces-unassigned" | "governance" | "security" | "compliance" | "audit" | "models" | "costs" | "docs";

export const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<Page>("dashboard");
  const [currentUser, setCurrentUser] = useState<SessionUser | null>(authStorage.getUser());
  // El cambio de la propia contraseña vive acá y no en una página del nav: es de CUALQUIER
  // rol, y la única pantalla con campos de contraseña (Usuarios) es admin-only. Sin esto, la
  // credencial que reparte el administrador al dar de alta a alguien no la puede rotar su
  // propio dueño.
  const [cambiarPassword, setCambiarPassword] = useState(false);

  // Cada item declara el GRUPO DE SUPERFICIE de la matriz que representa; `surface: null` = sin
  // superficie gateada (visible a toda sesión de consola). La visibilidad sale de `canView` sobre
  // ese grupo — celda por celda contra `matriz-roles.md`. Reconciliación 017 vs el estado previo:
  //   playground → chat_playground (lectura = 403 → deja de verlo; resto igual)
  //   costs/audit/firewall → vitrinas_lectura (suman `lectura`)
  //   users → gestion_iam · governance/security → config_producto (suman la R del auditor)
  //   models → FUERA de la matriz 017 (gate explícito admin+developer vía `legacyRoles`, ver abajo)
  // El "corte fino" (que la página esconda botones de escritura para el rol de solo lectura vía
  // los helpers de `ROLE_PERMISSIONS`) es trabajo por-página posterior (US1) — acá se reconcilia
  // la VISIBILIDAD del nav a la matriz; los helpers quedan listos para ese cableado. `legacyRoles`
  // es la escotilla explícita para superficies que la matriz 017 todavía no nombra.
  const navigation: { id: Page; name: string; icon: typeof LayoutDashboard; surface: SurfaceGroup | null; legacyRoles?: string[] }[] = [
    { id: "dashboard", name: "Panel Principal", icon: LayoutDashboard, surface: null },
    { id: "playground", name: "Playground", icon: FlaskConical, surface: "chat_playground" },
    // `models` NO está en ningún grupo del contrato 017 (GET /models = require_authenticated;
    // POST/PATCH/DELETE = require_role("admin","developer")). Mapearlo a config_producto le
    // quitaba el nav a `developer`, que el backend SÍ deja gestionar = under-permit. Gate
    // explícito = comportamiento previo, cero regresión. Pendiente decisión de contrato (follow-up).
    { id: "models", name: "Modelos & Ollama", icon: Boxes, surface: null, legacyRoles: ["admin", "developer"] },
    { id: "costs", name: "Costos", icon: Wallet, surface: "vitrinas_lectura" },
    { id: "users", name: "Usuarios & Presupuestos", icon: UsersIcon, surface: "gestion_iam" },
    // Spec 044 (T044): mismo grupo de superficie que Usuarios — es gestión de identidad/
    // acceso (a quién pertenece cada espacio), no config de producto.
    { id: "workspaces-unassigned", name: "Espacios sin asignar", icon: FolderOpen, surface: "gestion_iam" },
    { id: "governance", name: "Gobernanza", icon: Scale, surface: "config_producto" },
    { id: "security", name: "Seguridad y Guardianes", icon: ShieldCheck, surface: "config_producto" },
    { id: "compliance", name: "Políticas de Cumplimiento", icon: ClipboardCheck, surface: "compliance_config" },
    { id: "audit", name: "Logs de Auditoría", icon: ScrollText, surface: "vitrinas_lectura" },
    { id: "firewall", name: "Conexiones en vivo", icon: Activity, surface: "vitrinas_lectura" },
    { id: "docs", name: "Documentación", icon: BookOpen, surface: null },
  ];

  // Pantalla de retorno del IdP (spec 017 US2). Esta SPA no usa un router de URLs — todo
  // el resto navega por `currentPage` en memoria, no por la barra de direcciones — así que
  // no hay un <Route> donde colgar esto: se detecta el pathname UNA vez al montar y se
  // vuelve a "/" (`history.replaceState`) apenas el callback resuelve, éxito o error. El
  // Caddy del frontend sirve la SPA para cualquier ruta (`try_files {path} /index.html`,
  // deploy/docker/Caddyfile.frontend), así que la navegación completa que hace Microsoft de
  // vuelta acá carga igual este bundle.
  const [route, setRoute] = useState<string>(() => window.location.pathname);
  const [ssoLoginError, setSsoLoginError] = useState<string | undefined>(undefined);

  const handleLogin = (user: SessionUser) => {
    setCurrentUser(user);
    setCurrentPage("dashboard");
  };

  const handleLogout = () => {
    authStorage.clear();
    setCurrentUser(null);
  };

  const volverARaiz = () => {
    window.history.replaceState(null, "", "/");
    setRoute("/");
  };

  const handleSsoCallbackSuccess = (user: SessionUser) => {
    volverARaiz();
    handleLogin(user);
  };

  const handleSsoCallbackError = (message: string) => {
    setSsoLoginError(message);
    volverARaiz();
  };

  if (route === "/sso/callback") {
    return <SsoCallbackPage onSuccess={handleSsoCallbackSuccess} onError={handleSsoCallbackError} />;
  }

  if (!currentUser) {
    return <LoginPage onLoginSuccess={handleLogin} initialError={ssoLoginError} />;
  }

  // Usuario final → portal, JAMÁS la consola de administración. El login devuelve el rol
  // canónico post-013 ("client", users.py) y authStorage lo guarda pasado por toLegacyRole
  // (services/auth.ts), que deja "client" tal cual salvo cuando display_label es
  // "clinician"/"developer". Por eso el gate cubre "client" y "clinician" (el usuario final
  // histórico); "developer" conserva la consola, igual que en el predecesor. `lectura` NO va al
  // portal: entra a la consola en modo solo-vitrinas (el nav lo deja ver únicamente las vitrinas
  // de lectura — costos/auditoría/conexiones — vía `canView`).
  if (currentUser.role === "client" || currentUser.role === "clinician") {
    return <UserPortal user={currentUser} onLogout={handleLogout} />;
  }

  const visibleNav = navigation.filter(item =>
    item.legacyRoles
      ? item.legacyRoles.includes(currentUser.role)
      : item.surface === null || canView(currentUser.role, item.surface)
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
        {currentPage === "workspaces-unassigned" && <WorkspacesUnassignedPage />}
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
