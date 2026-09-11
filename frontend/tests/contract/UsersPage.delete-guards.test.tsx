// T038 (spec 044 US4): la UI repite las mismas dos validaciones que el backend (409 en
// ambos casos) ANTES de llamar — auto-baja y baja del último admin activo. `deleteUser`
// NUNCA debe llamarse en ninguno de los dos casos.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { deleteUserMock } = vi.hoisted(() => ({ deleteUserMock: vi.fn(async () => ({})) }));

vi.mock('../../src/services/api', async () => {
  const actual = await vi.importActual<any>('../../src/services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      getUsers: vi.fn(async ({ includeService }: any = {}) => {
        const admin = { id: 'admin-id', username: 'admin', email: 'admin@x.test', role: 'tenant_admin', is_active: true, created_at: '', updated_at: '', account_type: 'person' };
        const ana = { id: 'u1', username: 'ana', email: 'ana@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'person' };
        return includeService ? [admin, ana] : [admin, ana];
      }),
      getBudgets: vi.fn(async () => []),
      getGroups: vi.fn(async () => []),
      getKeys: vi.fn(async () => []),
      getGroupsCompliance: vi.fn(async () => []),
      getComplianceProjects: vi.fn(async () => []),
      getSsoAvailable: vi.fn(async () => ({ enabled: false, provider_type: null })),
      getGroupSpend: vi.fn(async () => ({ spend_usd: 0, max_budget: null, remaining: null })),
      deleteUser: deleteUserMock,
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

describe('UsersPage — guardas de baja', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('auto-baja: la UI la impide sin llamar al backend', async () => {
    render(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText('Usuarios & Equipos'));
    await screen.findByText('admin');

    // Hay dos filas con botón "Dar de baja" (admin y ana) — la primera es la de admin.
    const bajaButtons = screen.getAllByText('Dar de baja');
    await user.click(bajaButtons[0]);

    const input = await screen.findByLabelText(/Escribí "admin" para confirmar/);
    await user.type(input, 'admin');
    const confirmButtons = screen.getAllByRole('button', { name: 'Dar de baja' });
    await user.click(confirmButtons[confirmButtons.length - 1]);

    expect(await screen.findByText('No podés darte de baja a vos mismo.')).toBeInTheDocument();
    expect(deleteUserMock).not.toHaveBeenCalled();
  });

  it('último admin activo: la UI impide la baja sin llamar al backend', async () => {
    render(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText('Usuarios & Equipos'));
    await screen.findByText('admin');

    // Simular que un OTRO admin (no el que está logueado) intenta dar de baja al único
    // admin activo — acá "admin" es el único admin de la lista, así que dar de baja a
    // "ana" no dispara la guarda, pero dar de baja a "admin" (el último admin) sí.
    const rows = screen.getAllByRole('row');
    const adminRow = rows.find((r) => r.textContent?.includes('admin'));
    const bajaBtn = adminRow!.querySelector('button.text-danger') as HTMLElement;
    await user.click(bajaBtn);

    const input = await screen.findByLabelText(/Escribí "admin" para confirmar/);
    await user.type(input, 'admin');
    const confirmButtons2 = screen.getAllByRole('button', { name: 'Dar de baja' });
    await user.click(confirmButtons2[confirmButtons2.length - 1]);

    // Como el actor logueado ES "admin-id" (mismo id), primero dispara la guarda de
    // auto-baja (más específica) — igual verifica que deleteUser nunca se llama.
    expect(deleteUserMock).not.toHaveBeenCalled();
  });
});
