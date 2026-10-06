// `authStorage.save` colapsa tenant_admin/super_admin a `admin` para los gates del panel;
// guarda además el rol canónico para poder distinguirlos (sólo el super_admin asigna
// «Auditor»). Sin el canónico no se puede ofrecer ni ocultar esa opción con fundamento.
import { describe, it, expect, beforeEach } from 'vitest';
import { authStorage, canAssignComplianceRoles } from '../../src/services/auth';

describe('rol canónico en la sesión', () => {
  beforeEach(() => localStorage.clear());

  it('guarda el canónico junto al rol colapsado', () => {
    authStorage.save('t', { id: '1', username: 's', email: 's@x.test', role: 'super_admin' } as any);
    expect(authStorage.getUser()).toMatchObject({ role: 'admin', canonical_role: 'super_admin' });
  });

  it('un tenant_admin colapsa igual a `admin` pero no es super_admin', () => {
    authStorage.save('t', { id: '1', username: 'a', email: 'a@x.test', role: 'tenant_admin' } as any);
    expect(authStorage.getUser()).toMatchObject({ role: 'admin', canonical_role: 'tenant_admin' });
  });

  it('re-guardar la sesión (ej. tras cambiar la contraseña) no pisa el canónico con el colapsado', () => {
    authStorage.save('t', { id: '1', username: 's', email: 's@x.test', role: 'super_admin' } as any);
    authStorage.save('t', { ...authStorage.getUser()!, must_change_password: false });
    expect(authStorage.getUser()!.canonical_role).toBe('super_admin');
  });

  it('canAssignComplianceRoles: sólo super_admin; sin canónico o sin sesión, no', () => {
    expect(canAssignComplianceRoles({ role: 'admin', canonical_role: 'super_admin' } as any)).toBe(true);
    expect(canAssignComplianceRoles({ role: 'admin', canonical_role: 'tenant_admin' } as any)).toBe(false);
    expect(canAssignComplianceRoles({ role: 'admin' } as any)).toBe(false);
    expect(canAssignComplianceRoles(null)).toBe(false);
  });
});
