// T057 (spec 044 US6): pruebas de contrato explícitas para los contratos 4, 5 y 6 de la
// 043 del lado del panel — lo que no queda cubierto por las pruebas de UsersPage
// (T008-T038), que ejercitan el flujo completo pero no verifican el shape exacto de cada
// función de `api.ts` contra la respuesta real documentada en cada contrato.
import { describe, it, expect, beforeEach, vi } from 'vitest';

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  localStorage.setItem('sentinel_session_token', 'test-token');
});

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

describe('Contrato 4 (043) — tipo de cuenta en usuarios', () => {
  it('getUsers({includeService:true}) pide ?include_service=true y devuelve purpose/account_type', async () => {
    const { api } = await import('../../src/services/api');
    fetchMock.mockImplementation((url: string) =>
      jsonResponse([
        { id: 'u1', username: 'ana', email: 'ana@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'human' },
        { id: 'svc1', username: 'svc.rag-masking', email: 'svc@x.test', role: 'client', is_active: true, created_at: '', updated_at: '', account_type: 'service', purpose: 'Protección de documentos antes de indexarlos' },
      ])
    );
    const users = await api.getUsers({ includeService: true });
    expect(fetchMock.mock.calls[0][0]).toContain('?include_service=true');
    expect(users.find((u) => u.account_type === 'service')?.purpose).toBe('Protección de documentos antes de indexarlos');
  });

  it('getUsers() sin argumentos no agrega el query param', async () => {
    const { api } = await import('../../src/services/api');
    fetchMock.mockImplementation(() => jsonResponse([]));
    await api.getUsers();
    expect(fetchMock.mock.calls[0][0]).not.toContain('include_service');
  });
});

describe('Contrato 5 (043) — actualización parcial y baja', () => {
  it('patchUser manda PATCH con solo los campos dados, nunca el objeto completo', async () => {
    const { api } = await import('../../src/services/api');
    fetchMock.mockImplementation(() => jsonResponse({ id: 'u1', username: 'ana', email: 'ana@x.test', role: 'compliance_officer', is_active: true, created_at: '', updated_at: '' }));
    await api.patchUser('u1', { role: 'compliance_officer' });
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain('/users/u1');
    expect(opts.method).toBe('PATCH');
    expect(JSON.parse(opts.body)).toEqual({ role: 'compliance_officer' });
  });

  it('deleteUser manda DELETE y devuelve el resumen de espacios afectados', async () => {
    const { api } = await import('../../src/services/api');
    fetchMock.mockImplementation(() => jsonResponse({ status: 'deactivated', id: 'u1', workspaces_unassigned: 2 }));
    const result = await api.deleteUser('u1');
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain('/users/u1');
    expect(opts.method).toBe('DELETE');
    expect(result.workspaces_unassigned).toBe(2);
  });

  it('deleteUser propaga el 409 del backend (auto-baja / último admin) como error legible', async () => {
    const { api, ApiError } = await import('../../src/services/api');
    fetchMock.mockImplementation(() => jsonResponse({ detail: 'No podés darte de baja a vos mismo.' }, 409));
    await expect(api.deleteUser('u1')).rejects.toBeInstanceOf(ApiError);
  });
});

describe('Contrato 6 (043) — nombres neutros', () => {
  it('updateModelCredential manda engine_params, nunca litellm_params', async () => {
    const { api } = await import('../../src/services/api');
    fetchMock.mockImplementation(() => jsonResponse({}));
    await api.updateModelCredential('gpt-4o-mini', { api_key: 'x' });
    const [, opts] = fetchMock.mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body).toHaveProperty('engine_params');
    expect(body).not.toHaveProperty('litellm_params');
  });
});
