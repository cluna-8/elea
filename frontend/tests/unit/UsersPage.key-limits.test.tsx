// 057: en «Llaves Virtuales» cada fila trae «Editar límites»; guardar llama a PATCH /keys/{id} y recarga la lista.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { updateKeyLimitsMock, getKeysMock } = vi.hoisted(() => ({ updateKeyLimitsMock: vi.fn(), getKeysMock: vi.fn() }));

vi.mock('../../src/services/api', async () => {
  const actual = await vi.importActual<any>('../../src/services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      getUsers: vi.fn(async () => []),
      getBudgets: vi.fn(async () => []),
      getGroups: vi.fn(async () => []),
      getKeys: getKeysMock,
      getGroupsCompliance: vi.fn(async () => []),
      getComplianceProjects: vi.fn(async () => []),
      getSsoAvailable: vi.fn(async () => ({ enabled: false, provider_type: null })),
      getGroupSpend: vi.fn(async () => ({ spend_usd: 0, max_budget: null, remaining: null })),
      updateKeyLimits: updateKeyLimitsMock,
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

const llave = (rpm: number, tpm: number) => ({
  id: 'k1', name: 'Kit claude_desktop', key_preview: 'sk-sentinel-…abcd', user_id: null, group_id: null,
  tool_type: 'claude-desktop', is_active: true, rpm_limit: rpm, tpm_limit: tpm, created_at: '2026-10-07T10:00:00Z',
  spend_usd: null,
});

describe('UsersPage — editar límites de una llave', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getKeysMock.mockResolvedValueOnce([llave(60, 100000)]).mockResolvedValue([llave(120, 1000000)]);
  });

  it('guarda los límites nuevos y recarga la lista con lo que quedó', async () => {
    updateKeyLimitsMock.mockResolvedValueOnce(llave(120, 1000000));
    render(<UsersPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByText('Llaves Virtuales'));
    expect(await screen.findByText(/60 rpm/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Editar límites/i }));
    const rpm = await screen.findByLabelText(/Límite RPM/i);
    const tpm = screen.getByLabelText(/Límite TPM/i);
    await user.clear(rpm); await user.type(rpm, '120');
    await user.clear(tpm); await user.type(tpm, '1000000');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(updateKeyLimitsMock).toHaveBeenCalledWith('k1', { rpm_limit: 120, tpm_limit: 1000000 });
    expect(await screen.findByText(/120 rpm/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Límite RPM/i)).not.toBeInTheDocument();      // el modal se cerró
  });
});
