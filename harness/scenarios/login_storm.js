// login_storm.js — tormenta de login del gate 250 (spec 035, T024/T035; US2).
// 250 logins concentrados en la ventana (POST /api/v1/users/login) para examinar el
// arranque en frío del plano de auth (bcrypt + emisión de JWT) bajo entrada masiva. El
// gate declara el scenario `login_storm` (rate = población / 10m); esta función es su exec.
import http from 'k6/http';
import { check } from 'k6';
import { API, pickIdentity, recordLatency, phaseOf, metrics } from './common.js';

export function login() {
  const id = pickIdentity('login');
  const phase = phaseOf();
  const t0 = Date.now();
  const res = http.post(API + '/users/login',
    JSON.stringify({ username: id.username, password: id.password }),
    { headers: { 'Content-Type': 'application/json' },
      tags: { surface: 'login', phase: phase } });
  recordLatency('login', phase, Date.now() - t0);

  const ok = check(res, { 'login 200': function (r) { return r.status === 200; } });
  if (!ok) metrics.harness_errors.add(1);
}
