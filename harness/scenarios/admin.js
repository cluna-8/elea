// admin.js — superficie admin/paneles (spec 035, T024). GETs de los paneles que consumen
// tenant_admin y compliance_officer, con JWT. Ejercita el plano de lectura del backend
// (users/keys/budgets/audit-logs/health) que compite por Postgres+Prisma bajo carga.
import http from 'k6/http';
import { check } from 'k6';
import { API, pickIdentity, authHeaders, recordLatency, phaseOf, metrics } from './common.js';

// Paneles de solo-lectura (los GET reales del backend, prefijo /api/v1).
const PANELS = ['/users', '/keys', '/budgets', '/audit-logs', '/health'];

export function admin() {
  const id = pickIdentity('admin');
  const headers = authHeaders(id, 'admin'); // JWT (tenant_admin / compliance_officer)
  if (!headers) { metrics.harness_errors.add(1); return; }

  const phase = phaseOf();
  const t0 = Date.now();
  let worst = 0;
  for (let i = 0; i < PANELS.length; i++) {
    const res = http.get(API + PANELS[i], {
      headers: headers, tags: { surface: 'admin', panel: PANELS[i], phase: phase },
    });
    check(res, { 'panel sin 5xx': function (r) { return r.status < 500; } });
    if (res.timings && res.timings.duration > worst) worst = res.timings.duration;
  }
  // la latencia de la "sesión de panel" = el peor panel de la ronda.
  recordLatency('admin', phase, Date.now() - t0);
}
