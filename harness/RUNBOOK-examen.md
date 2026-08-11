# RUNBOOK — correr el examen (gate 125 oficial)

Secuencia operativa de punta a punta, copy-paste. **Sólo operativa**: el porqué de cada
criterio vive en [`README.md`](README.md) y en
[`specs/035-load-harness/`](../specs/035-load-harness/).

## Reglas duras (antes de tocar nada)

- **Nunca** contra el VPS de producción ni contra una instalación de cliente (FR-011). El
  examen corre en el project Hetzner aislado `guardian-itv` y en ninguna otra parte.
- El token del project se llama **`H_CLOUD_ITV`** en Vaultwarden. Se exporta por entorno;
  su VALOR no se escribe en un archivo del repo, ni en un ticket, ni en un chat.
- `backend/scripts/issue_dev_license.py` **REGENERA el keyset** y deja `invalid` cualquier
  licencia ya emitida: sólo contra stacks **descartables** como éste, jamás contra un
  stack vivo de cliente. Este runbook no lo usa: genera su propio par de test efímero.
- La caja del examen se destruye al terminar. Todo lo que viva sólo en ella (par de firma,
  licencia, pool de credenciales) muere con ella, y está bien.
- `--seed` es el MISMO en el seeder y en el orquestador. Si difieren, las passwords
  derivadas no autentican y el examen falla en masa por una causa que en el summary de k6
  sólo se ve como `harness_errors`.

```bash
export HCLOUD_TOKEN=…            # valor del token H_CLOUD_ITV (Vaultwarden), sólo en la shell
export ITV_SEED=…                # semilla del run (secreto del run, fuera del repo)
export ITV_RUN_ID=20260811-g125-01
```

## 1. Infra (OpenTofu) — servidores primero, firewall después

El firewall de egress se aplica **después** de precargar las imágenes: una vez cerrado, el
SUT no puede hacer pull de ningún lado.

```bash
cd harness/infra
tofu init
# 1a) sólo las cajas y la red (el firewall queda para el paso 3)
tofu apply \
  -target=hcloud_network.itv -target=hcloud_network_subnet.itv \
  -target=hcloud_server.sut -target=hcloud_server.gen \
  -target=hcloud_server_network.sut -target=hcloud_server_network.gen \
  -var 'ssh_key_names=["itv-op"]' -var "admin_ssh_cidrs=[\"$(curl -s ifconfig.me)/32\"]"

SUT_IP=$(tofu output -raw sut_public_ip)
tofu output -json fingerprint_hardware > /tmp/itv-hardware.json   # va al fingerprint
```

## 2. Precarga de imágenes (docker save/load)

```bash
# desde la máquina que tiene las imágenes pinneadas del release
./preload-images.sh "$SUT_IP" \
  ghcr.io/basa/backend@sha256:… \
  ghcr.io/basa/frontend@sha256:… \
  ghcr.io/basa/litellm@sha256:… \
  ghcr.io/basa/nlp-analyzer@sha256:…
```

Verificar en el SUT antes de cerrar el egress:

```bash
ssh root@"$SUT_IP" 'docker images --digests | grep basa'
```

## 3. Cerrar el egress (deny-out)

```bash
cd harness/infra
tofu apply -var 'ssh_key_names=["itv-op"]' -var "admin_ssh_cidrs=[\"$(curl -s ifconfig.me)/32\"]"
# comprobación: el SUT ya no sale a internet, pero sí ve la red privada
ssh root@"$SUT_IP" 'curl -s -m 5 https://api.anthropic.com >/dev/null && echo "❌ HAY EGRESS" || echo "✓ egress bloqueado"'
ssh root@"$SUT_IP" 'curl -s -m 5 http://10.0.0.20:8080/control/report >/dev/null && echo "✓ ve el stub"'
```

Sin este candado, un alias mal apuntado podría salir a un proveedor real y el SLO (c) —cero
canarios crudos— dejaría de significar algo.

## 4. Stack del examen + licencia de test descartable

### 4a. Perfil y arranque

```bash
cd deploy/clients/itv-examen
cp client.env.example client.env      # STUB_URL=http://10.0.0.20:8080, digests reales
cp branding.env.example branding.env
../../release/render_profile.sh itv-examen

DC="docker compose --env-file rendered/instance.env \
  -f ../../docker/compose.prod.yml -f compose.itv-examen.override.yml --profile selfhosted"
$DC up -d
```

### 4b. Par de firma EFÍMERO + licencia de 130 seats

La privada del kid `basa-dev-2026b` (licencia de la Cámara: 25 seats) está bajo custodia de
JF y **no se usa acá**. Se genera un par propio dentro del SUT: la pública entra al keyset
del contenedor y la privada vive en `/tmp` del contenedor — muere con él.

`kid = itv-examen-2026` a propósito **no** empieza con `basa-dev-`, así que no depende del
opt-in `BASA_ALLOW_DEV_LICENSE`. 130 seats = los 119 del gate 125 + holgura (ampliar en
caliente son ~5 min de 402 intermitentes).

```bash
# 1) par Ed25519 dentro del contenedor: pública → keyset, privada → /tmp (0600)
$DC exec -T backend python - <<'PY'
import os, pathlib
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KID = "itv-examen-2026"
priv = Ed25519PrivateKey.generate()
pub = priv.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
keyset = pathlib.Path("/app/src/keys/basa_public_keys.pem")
keyset.write_text(
    "# keyset EFÍMERO del examen ITV — muere con este contenedor.\n"
    f"# generado: {datetime.now(timezone.utc).isoformat()}\n"
    f"# key_id: {KID}\n{pub}")
p = pathlib.Path("/tmp/itv-examen-2026.pem")
fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, priv.private_bytes(encoding=serialization.Encoding.PEM,
                                format=serialization.PrivateFormat.PKCS8,
                                encryption_algorithm=serialization.NoEncryption()))
os.close(fd)
print("keyset:", keyset, "| privada efímera:", p)
PY

# 2) licencia firmada (issue_license.py VERIFICA contra el keyset antes de escribir)
$DC exec -T backend python scripts/issue_license.py \
  --key /tmp/itv-examen-2026.pem \
  --kid itv-examen-2026 \
  --lic-id lic_itv_examen_130 \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --distributor-id d_basa --pool-id pool_itv \
  --max-seats 130 --expiry 2026-08-18T00:00:00Z \
  --out /app/config/licenses/client.lic --force

# 3) la privada ya no hace falta: se borra
$DC exec -T backend rm -f /tmp/itv-examen-2026.pem

# 4) reinicio para que el backend relea keyset + licencia
$DC restart backend
$DC exec -T backend curl -sf http://localhost:8000/health >/dev/null && echo "✓ backend arriba"
```

> Si el contenedor `backend` se recrea (`up -d --force-recreate`, cambio de imagen), el
> keyset efímero se pierde y la licencia queda `invalid` (kid desconocido → 403 en todas
> las altas). Repetir 4b completo.

### 4c. Stub del harness en el generador

```bash
GEN_IP=$(cd harness/infra && tofu output -raw gen_public_ip)
ssh root@"$GEN_IP" \
  'cd /opt/basa-guardian-itv/harness && \
   nohup python -m uvicorn basa_harness.stub.server:app --host 0.0.0.0 --port 8080 \
     > /var/log/itv-stub.log 2>&1 &'
ssh root@"$GEN_IP" 'curl -sf http://127.0.0.1:8080/control/report >/dev/null && echo "✓ stub arriba"'
```

El puerto 8080 es el mismo que `STUB_URL`/`BASA_GW_ANTHROPIC_BASE` del perfil: el SUT le
manda el tráfico y el orquestador le habla por `/control` — una sola app.

> Los pasos 5 y 6 se corren **desde el generador** (ahí están el checkout del harness y
> `bin/k6`), no desde la laptop.

## 5. Seed de la población (gate 125) + pool de credenciales

El pool es **material de run**: 0600, fuera del repo, y no se publica con la evidencia.

```bash
cd harness
install -d -m 700 /run/itv
python -m basa_harness.seeder.seed \
  --gate 125 \
  --backend-url http://10.0.0.10:8000 \
  --seed "$ITV_SEED" \
  --emit-credentials /run/itv/pool-g125.json
echo "exit=$?"      # tiene que ser 0
```

| Salida | Qué significa | Qué hacer |
|---|---|---|
| `exit 0` | 119 seats + 6 cuentas admin creados, pool con `basa_key` en todas las identidades de extensión/coding | seguir |
| `❌ licencia insuficiente` | la licencia no da para 119 seats | rehacer 4b con más `--max-seats` |
| `❌ … basa_key` (exit 3) | las Connections ya existían: la key en claro **no** es recuperable | `$DC down -v && $DC up -d`, repetir 4b y 5 |
| `❌ … OTRA semilla` | la DB fue sembrada con otro `--seed` | `$DC down -v` y repetir con la semilla del run |

Entre runs, sin crear nada (valida además que las keys del pool siguen autenticando contra
`/gw/whoami`):

```bash
python -m basa_harness.seeder.seed --gate 125 --backend-url http://10.0.0.10:8000 \
  --seed "$ITV_SEED" --verify-only --emit-credentials /run/itv/pool-g125.json
```

## 6. La corrida

```bash
cd harness
python -m basa_harness.orchestrator \
  --gate 125 \
  --backend-url http://10.0.0.10:8000 \
  --stub-url http://10.0.0.20:8080 \
  --pool-file /run/itv/pool-g125.json \
  --reconcile http \
  --seed "$ITV_SEED" \
  --run-id "$ITV_RUN_ID"
```

- `--pool-file` aporta las `basa_key` (extensión/coding) **y** la credencial
  `compliance_officer` que lee `audit_logs`. La password nunca va por argv: `ps` no la ve.
- `--reconcile http` cuenta las filas de auditoría del producto en la ventana del run
  (t0 = antes de k6, t1 = al cerrarlo). **Un gate oficial se corre siempre con esto**: sin
  él, los SLO (b) y (d) no se pueden computar y el run aborta al reconciliar.
- Salida: `runs/$ITV_RUN_ID/` con `verdict.json`, `fingerprint.json`, `reporte.md`,
  `reconciliation.json` (el conteo que decidió (b) y (d)) y el `summary.json` de k6.
- Exit code: `0` PASS · `1` FAIL (examen válido, el producto violó un SLO) · `2` run no
  completado (INVALID: no hay veredicto).

**Abortos fail-closed que pueden aparecer y qué significan** (ninguno es un FAIL del
producto: son «no se puede certificar»):

| Mensaje | Causa | Qué hacer |
|---|---|---|
| `precondición de config no cumplida` | el stack no cumple `stack_config_required` (masking, NLP…) | corregir el perfil y volver a empezar — no se generó carga |
| `identidad(es) de extensión/coding sin basa_key` | pool sin material | volver al paso 5 (tabla de arriba) |
| `el filtro de ventana NO se está aplicando` | el backend descartó las fechas y contaría la tabla entera | no certificar; abrir issue al core con la evidencia |
| `el producto registró N fila(s) de bloqueo … el guion contó 0` | hubo bloqueos que el guion no ve (k6 no incrementa `observed_blocks`) | mirar las filas a mano (`GET /api/v1/audit-logs?estado=bloqueados`) antes de decidir |
| `la credencial … no autentica` | el pool es de otra semilla/instalación | re-seedear contra stack fresco |

## 7. Recolección de artefactos y destroy

El directorio del run contiene `pool.json` con **passwords y keys en claro** (0600): NO se
publica con la evidencia.

```bash
cd harness
tar czf "/tmp/$ITV_RUN_ID.tgz" --exclude='pool.json' -C runs "$ITV_RUN_ID"
scp "/tmp/$ITV_RUN_ID.tgz" itv-runs:/srv/itv-runs/          # plataforma de resultados R3

# logs del producto de la ventana del run (evidencia pesada)
ssh root@"$SUT_IP" "cd /opt/itv && docker compose logs --no-color > /tmp/$ITV_RUN_ID-sut.log"
scp root@"$SUT_IP":/tmp/"$ITV_RUN_ID"-sut.log /srv/itv-runs/

# material de run: se destruye con la caja, pero también acá
shred -u /run/itv/pool-g125.json

cd infra && tofu destroy \
  -var 'ssh_key_names=["itv-op"]' -var "admin_ssh_cidrs=[\"$(curl -s ifconfig.me)/32\"]"
```

> Entre gates del mismo día (125 → drill), en vez de destruir: `$DC down -v && $DC up -d` +
> repetir 4b y 5. El reset de DB es lo que mata el drift entre exámenes.
