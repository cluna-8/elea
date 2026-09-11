import React, { useEffect, useState } from "react";
import { api, WorkspaceUnassigned, User } from "../services/api";
import { Card, PageHeader, Button, Table, inputBaseClass } from "../components/ui";

// Spec 043 (US1, contrato 1) + spec 044 (T044): espacios heredados de una migración
// (instalación previa a esta feature) sin ningún miembro todavía — el backend ya los
// aísla en `GET /workspaces?status_filter=unassigned` (solo admins, 403 para el resto).
// Asignarles un dueño es lo único que hace falta para que vuelvan a aparecer en el Hub
// de la persona correspondiente (mismo endpoint que el Hub usa para su propio modal
// "Sin asignar" — este es el equivalente del lado del panel de administración).
export const WorkspacesUnassignedPage: React.FC = () => {
  const [workspaces, setWorkspaces] = useState<WorkspaceUnassigned[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [usernameByWorkspace, setUsernameByWorkspace] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [ws, us] = await Promise.all([
        api.getUnassignedWorkspaces(),
        api.getUsers(),
      ]);
      setWorkspaces(ws);
      setUsers(us);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "No se pudieron consultar los espacios sin asignar.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleAssign = async (ws: WorkspaceUnassigned) => {
    const username = (usernameByWorkspace[ws.id] || "").trim();
    if (!username) return;
    setAssigning(ws.id);
    setMsg(null);
    try {
      await api.assignWorkspaceMember(ws.id, username);
      setMsg(`"${ws.display_name}" asignado a "${username}".`);
      await fetchData();
    } catch (err: any) {
      setError(err?.message || "No se pudo asignar el espacio.");
    } finally {
      setAssigning(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Espacios sin asignar"
        subtitle="Espacios de Eleia Hub heredados de una migración, todavía sin dueño. Asignales un dueño para que vuelvan a aparecer en su Hub."
      />

      {error && (
        <div className="bg-danger-bg border border-danger/20 text-danger px-4 py-2.5 rounded-md text-xs">
          {error}
        </div>
      )}
      {msg && (
        <div className="bg-ok-bg border border-ok/20 text-ok px-4 py-2.5 rounded-md text-xs">
          {msg}
        </div>
      )}

      <Card title={`Espacios sin asignar (${workspaces.length})`}>
        {loading ? (
          <p className="text-xs text-text-secondary">Cargando…</p>
        ) : workspaces.length === 0 ? (
          <p className="text-xs text-text-secondary">No hay espacios sin asignar.</p>
        ) : (
          <Table className="text-xs">
            <Table.Head>
              <Table.Row>
                <Table.HeaderCell>Espacio</Table.HeaderCell>
                <Table.HeaderCell>Asignar a</Table.HeaderCell>
                <Table.HeaderCell />
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {workspaces.map((ws) => (
                <Table.Row key={ws.id}>
                  <Table.Cell className="font-semibold text-text-primary">{ws.display_name}</Table.Cell>
                  <Table.Cell>
                    <input
                      type="text"
                      list="workspaces-unassigned-users"
                      value={usernameByWorkspace[ws.id] || ""}
                      onChange={(e) => setUsernameByWorkspace((prev) => ({ ...prev, [ws.id]: e.target.value }))}
                      placeholder="Nombre de usuario del dueño"
                      className={inputBaseClass}
                    />
                  </Table.Cell>
                  <Table.Cell>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleAssign(ws)}
                      disabled={assigning === ws.id || !(usernameByWorkspace[ws.id] || "").trim()}
                    >
                      {assigning === ws.id ? "Asignando..." : "Asignar"}
                    </Button>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Card>
      <datalist id="workspaces-unassigned-users">
        {users.map((u) => <option key={u.id} value={u.username} />)}
      </datalist>
    </div>
  );
};
