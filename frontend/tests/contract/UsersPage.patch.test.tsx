// T037 (spec 044 US4): editar solo el rol o solo el email manda un PATCH PARCIAL — nunca
// reenvía los campos que la persona no tocó (a diferencia del viejo `updateUser` vía PUT).
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { patchUserMock } = vi.hoisted(() => ({ patchUserMock: vi.fn(async () => ({})) }));

vi.mock('../../src/services/api', async () => {
  const actual = await vi.importActual<any>('../../src/services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      getUsers: vi.fn(async ({ includeService }: any = {}) => {
        const persona = { id: 'u1', username: 'ana', email: 'ana@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'human' };
        return includeService ? [persona] : [persona];
      }),
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

describe('UsersPage — edición parcial', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('editar solo el email manda PATCH con únicamente ese campo', async () => {
    render(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText('Usuarios & Equipos'));
    await screen.findByText('ana');

    await user.click(screen.getByText('Editar'));
    const emailInput = await screen.findByDisplayValue('ana@x.test');
    await user.clear(emailInput);
    await user.type(emailInput, 'ana.nueva@x.test');
    await user.click(screen.getByText('Guardar'));

    expect(patchUserMock).toHaveBeenCalledTimes(1);
    expect(patchUserMock).toHaveBeenCalledWith('u1', { email: 'ana.nueva@x.test' });
  });

  it('no tocar nada no llama a patchUser', async () => {
    render(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText('Usuarios & Equipos'));
    await screen.findByText('ana');

    await user.click(screen.getByText('Editar'));
    await screen.findByDisplayValue('ana@x.test');
    await user.click(screen.getByText('Guardar'));

    expect(patchUserMock).not.toHaveBeenCalled();
  });
});
