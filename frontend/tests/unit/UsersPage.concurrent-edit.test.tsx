// T061 (edge case, spec 044 Polish): dos pestañas editando al mismo usuario — la segunda
// que guarda manda un PATCH parcial basado en SU PROPIA edición (no reenvía campos viejos
// de la primera), y el backend rechazándola con 409 (conflicto real, ej. username tomado
// por la primera edición) se muestra como error legible, sin romper la UI.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { patchUserMock } = vi.hoisted(() => ({ patchUserMock: vi.fn() }));

vi.mock('../../src/services/api', async () => {
  const actual = await vi.importActual<any>('../../src/services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      getUsers: vi.fn(async () => ([
        { id: 'u1', username: 'ana', email: 'ana@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'human' },
      ])),
      getBudgets: vi.fn(async () => []),
      getGroups: vi.fn(async () => []),
      getKeys: vi.fn(async () => []),
      getGroupsCompliance: vi.fn(async () => []),
      getComplianceProjects: vi.fn(async () => []),
      getSsoAvailable: vi.fn(async () => ({ enabled: false, provider_type: null })),
      getGroupSpend: vi.fn(async () => ({ spend_usd: 0, max_budget: null, remaining: null })),
      patchUser: patchUserMock,
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

describe('UsersPage — edición concurrente (dos pestañas)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('un 409 del backend (conflicto real) se muestra sin romper la pantalla', async () => {
    patchUserMock.mockRejectedValueOnce(Object.assign(new Error('El email \'ana2@x.test\' ya está en uso.'), { status: 409 }));

    render(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText('Usuarios & Equipos'));
    await screen.findByText('ana');

    await user.click(screen.getByText('Editar'));
    const emailInput = await screen.findByDisplayValue('ana@x.test');
    await user.clear(emailInput);
    await user.type(emailInput, 'ana2@x.test');
    await user.click(screen.getByText('Guardar'));

    expect(await screen.findByText("El email 'ana2@x.test' ya está en uso.")).toBeInTheDocument();
    // La pantalla sigue funcional: el modal de edición sigue abierto (no se cerró en
    // falso), con el email que la persona tipeó todavía visible.
    expect(screen.getByDisplayValue('ana2@x.test')).toBeInTheDocument();
  });
});
