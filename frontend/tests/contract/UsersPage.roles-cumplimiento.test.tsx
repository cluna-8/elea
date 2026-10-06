// El backend asigna `compliance_officer` («Auditor») y `super_admin` SÓLO a un super_admin
// (403 al tenant_admin). El panel no ofrece una opción que el backend le va a rechazar a
// quien mira: el alta y la edición de rol ocultan «Auditor» salvo para un super_admin.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { sesion } = vi.hoisted(() => ({ sesion: { actual: {} as any } }));

const persona = (id: string, username: string, role: string) => ({
  id, username, email: `${username}@x.test`, role, is_active: true, created_at: '',
  updated_at: '', account_type: 'person',
});

vi.mock('../../src/services/api', async () => {
  const actual = await vi.importActual<any>('../../src/services/api');
  return {
    ...actual,
    api: {
      ...actual.api,
      getUsers: vi.fn(async () => [
        { id: 'u1', username: 'ana', email: 'ana@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'person' },
        { id: 'u2', username: 'beto', email: 'beto@x.test', role: 'compliance_officer', is_active: true, created_at: '', updated_at: '', account_type: 'person' },
      ]),
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
  return { ...actual, authStorage: { ...actual.authStorage, getUser: () => sesion.actual } };
});

import { UsersPage } from '../../src/pages/UsersPage';

// `authStorage.save` colapsa tenant_admin y super_admin a `admin` (toLegacyRole): la sesión
// guarda además el rol canónico, que es lo que distingue a uno del otro.
const TENANT_ADMIN = { id: 'a', username: 'admin', role: 'admin', canonical_role: 'tenant_admin' };
const SUPER_ADMIN = { id: 's', username: 'root', role: 'admin', canonical_role: 'super_admin' };
const SESION_VIEJA = { id: 'a', username: 'admin', role: 'admin' }; // guardada antes del cambio

async function abrirTabUsuarios() {
  render(<UsersPage />);
  const user = userEvent.setup();
  await user.click(await screen.findByText('Usuarios & Equipos'));
  await screen.findByText('ana');
  return user;
}

const opciones = (select: HTMLElement) =>
  Array.from(select.querySelectorAll('option')).map((o) => o.textContent);

async function selectDeRolDelAlta(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText('Registrar Miembro'));
  const form = (await screen.findAllByText('Registrar Miembro')).pop()!.closest('div')!.parentElement!;
  const select = Array.from(form.querySelectorAll('select')).find((s) =>
    opciones(s as HTMLElement).includes('Administrador'));
  return select as HTMLElement;
}

describe('UsersPage — roles de cumplimiento sólo para super_admin', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('alta: el tenant_admin NO ve «Auditor»', async () => {
    sesion.actual = TENANT_ADMIN;
    const user = await abrirTabUsuarios();
    const opts = opciones(await selectDeRolDelAlta(user));
    expect(opts).not.toContain('Auditor');
    expect(opts).toEqual(expect.arrayContaining(['Especialista', 'Desarrollador', 'Solo Lectura', 'Administrador']));
  });

  it('alta: el super_admin SÍ ve «Auditor»', async () => {
    sesion.actual = SUPER_ADMIN;
    const user = await abrirTabUsuarios();
    expect(opciones(await selectDeRolDelAlta(user))).toContain('Auditor');
  });

  it('alta: una sesión sin rol canónico (guardada antes del cambio) lo oculta — falla cerrado', async () => {
    sesion.actual = SESION_VIEJA;
    const user = await abrirTabUsuarios();
    expect(opciones(await selectDeRolDelAlta(user))).not.toContain('Auditor');
  });

  it('edición de rol: el tenant_admin no ve «Auditor» al editar a un cliente', async () => {
    sesion.actual = TENANT_ADMIN;
    const user = await abrirTabUsuarios();
    await user.click(screen.getAllByText('Editar')[0]);
    const select = (await screen.findByDisplayValue('Cliente')) as HTMLElement;
    expect(opciones(select)).not.toContain('Auditor');
  });

  it('edición de rol: el super_admin ve «Auditor»', async () => {
    sesion.actual = SUPER_ADMIN;
    const user = await abrirTabUsuarios();
    await user.click(screen.getAllByText('Editar')[0]);
    const select = (await screen.findByDisplayValue('Cliente')) as HTMLElement;
    expect(opciones(select)).toContain('Auditor');
  });

  it('edición de rol: quien YA es Auditor lo sigue viendo seleccionado aunque el editor sea tenant_admin', async () => {
    sesion.actual = TENANT_ADMIN;
    const user = await abrirTabUsuarios();
    await user.click(screen.getAllByText('Editar')[1]);
    const select = (await screen.findByDisplayValue('Auditor')) as HTMLElement;
    expect(opciones(select)).toContain('Auditor');
  });
});
