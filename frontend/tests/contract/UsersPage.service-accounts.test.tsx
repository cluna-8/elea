// T036 (spec 044 US4): la sección "Cuentas de servicio" está plegada por default, de solo
// lectura (sin acciones de edición/baja), y esas cuentas NUNCA aparecen en la tabla
// principal de personas — bug real que motivó el contrato 4 de la 043 (diagnostico.md §4).
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../src/services/api', async () => {
  const actual = await vi.importActual<any>('../../src/services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      getUsers: vi.fn(async ({ includeService }: any = {}) => {
        const persona = { id: 'u1', username: 'ana', email: 'ana@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'person' };
        const servicio = { id: 'svc1', username: 'svc.rag-masking', email: 'svc@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'service', purpose: 'Enmascarado de documentos del Hub' };
        return includeService ? [persona, servicio] : [persona];
      }),
      getBudgets: vi.fn(async () => []),
      getGroups: vi.fn(async () => []),
      getKeys: vi.fn(async () => []),
      getGroupsCompliance: vi.fn(async () => []),
      getComplianceProjects: vi.fn(async () => []),
      getSsoAvailable: vi.fn(async () => ({ enabled: false, provider_type: null })),
      getGroupSpend: vi.fn(async () => ({ spend_usd: 0, max_budget: null, remaining: null })),
    },
  };
});

vi.mock('../../src/services/auth', async () => {
  const actual = await vi.importActual<any>('../../src/services/auth');
  return {
    ...actual,
    authStorage: { ...actual.authStorage, getUser: () => ({ id: 'admin-id', username: 'admin', role: 'admin' }) },
  };
});

import { UsersPage } from '../../src/pages/UsersPage';

describe('UsersPage — cuentas de servicio', () => {
  beforeEach(() => vi.clearAllMocks());

  it('la sección está plegada por default y las cuentas de servicio no están en la tabla principal', async () => {
    render(<UsersPage />);
    const user = userEvent.setup();

    // La tabla vive en la pestaña "Usuarios & Equipos", no en "Resumen" (tab inicial).
    await user.click(await screen.findByText('Usuarios & Equipos'));
    await screen.findByText('ana');

    // La cuenta de servicio NO aparece en ningún lado todavía (sección plegada).
    expect(screen.queryByText('svc.rag-masking')).not.toBeInTheDocument();

    const heading = await screen.findByText(/Cuentas de servicio \(1\)/);
    expect(heading).toBeInTheDocument();

    // Al desplegar, aparece con su propósito — y sigue sin estar en la tabla de personas.
    await user.click(screen.getByText('Mostrar'));

    expect(await screen.findByText('svc.rag-masking')).toBeInTheDocument();
    expect(screen.getByText('Enmascarado de documentos del Hub')).toBeInTheDocument();

    // La tabla principal de personas sigue teniendo solo a "ana".
    const personTable = screen.getByText('ana').closest('table');
    expect(personTable ? within(personTable).queryByText('svc.rag-masking') : null).toBeNull();
  });
});
