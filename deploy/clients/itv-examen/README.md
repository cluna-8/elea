# Perfil `itv-examen` — entorno de EXAMEN (no es un cliente real)

Perfil de despliegue del **banco de pruebas de carga (La ITV, spec 035)**. Levanta el
stack de producción REAL para medir los gates **125 / 250 / 500**, pero con todo el
egress apuntado a un **stub** y **bloqueado por firewall**. No hay ningún proveedor real
detrás ni ningún dato de cliente: la población y el corpus son 100% sintéticos.

> **No confundir con `camara-comercio/`**: ese es un piloto real. Este perfil existe sólo
> para el examen. Mismo mecanismo de perfiles (spec 020), estructura idéntica.

## Todo el tráfico pasa por el stub (los 4 cierres de R2)

1. **`config.yaml.tmpl`** — cada entrada de `model_list` es `openai/<alias>` → `${STUB_URL}/v1`
   con api_key dummy; los `fallbacks` sólo caen entre aliases stub-backed.
2. **`compose.itv-examen.override.yml`** — cablea `SENTINEL_GW_ANTHROPIC_BASE` (passthrough de
   suscripción Anthropic) al stub. compose.prod.yml no la pasa al backend (hallazgo R2) y
   no editamos ese archivo (territorio Falime): la agregamos como override.
3. **provider keys VACÍAS** en `client.env` (`OPENAI_API_KEY=`, `ANTHROPIC_API_KEY=`, …) —
   un alias mal apuntado a un proveedor real falla RUIDOSO en vez de gastar o fugar.
4. **egress bloqueado en el firewall** del SUT (Hetzner cloud firewall, deny de salida):
   el candado que convierte "creemos que todo pasa por el stub" en "no puede no pasar".

## Archivos

| Archivo | Qué es |
|---|---|
| `config.yaml.tmpl` | LiteLLM templado (100% stub-backed). |
| `client.env.example` | Overlay de entorno (STUB_URL, keys vacías, `SENTINEL_ALLOW_DEV_LICENSE`, imágenes). `*.env` está gitignored → se versiona el `.example`. |
| `branding.env.example` | Branding nominal del examen. |
| `auto_router.json` | Rutas del auto-router (targets = aliases stub-backed). |
| `brand.extension.json` | Branding de la extensión. |
| `compose.itv-examen.override.yml` | Cablea `SENTINEL_GW_ANTHROPIC_BASE` → stub. |
| `seed.yaml` | Vacío a propósito: la población la siembra el **seeder del harness** vía API, no el onboarding-as-data. |

## Desplegar (resumen)

```bash
cp client.env.example client.env         # rellenar STUB_URL y los digests de imagen
cp branding.env.example branding.env
../../release/render_profile.sh itv-examen        # → rendered/

# instalar la licencia definitiva ANTES de seedear (ver abajo), luego:
docker compose --env-file rendered/instance.env \
  -f ../../docker/compose.prod.yml \
  -f compose.itv-examen.override.yml \
  --profile selfhosted up -d
```

Después se siembra la población y se corre el gate: ver
[`harness/README.md`](../../../harness/README.md) § *Seeder + licencias del examen*.

## Licencias del examen — ⚠️ PENDIENTE (T022, requiere la privada de JF)

Los gates necesitan DOS licencias in-house (R5): **300 seats** (gates 125/250) y **500
seats** (gate 500). Se emiten con `backend/scripts/issue_license.py` (no destructivo:
verifica contra el keyset antes de escribir), reusando el **kid ya horneado
`sentinel-dev-2026b`**. La **clave privada de ese kid NO está en el repo** (`license_out/` es
gitignored, custodia de JF) y `issue_license.py` está bajo gate de Cristian en CODEOWNERS:
**este comando NO se ejecuta acá**, queda documentado como la operación exacta a correr.

```bash
# 300 seats — gates 125 y 250 (PENDIENTE: requiere signing_key_sentinel-dev-2026b.pem de JF)
python backend/scripts/issue_license.py \
  --key backend/scripts/license_out/signing_key_sentinel-dev-2026b.pem \
  --kid sentinel-dev-2026b \
  --lic-id lic_itv_examen_300 \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --distributor-id d_sentinel --pool-id pool_pilotos_sentinel \
  --max-seats 300 --expiry 2026-10-21T00:00:00Z \
  --out backend/scripts/license_out/itv-examen-300.lic

# 500 seats — gate 500 (mismo kid; sólo cambian max-seats, lic-id y out)
python backend/scripts/issue_license.py \
  --key backend/scripts/license_out/signing_key_sentinel-dev-2026b.pem \
  --kid sentinel-dev-2026b \
  --lic-id lic_itv_examen_500 \
  --tenant-id 00000000-0000-0000-0000-000000000001 \
  --distributor-id d_sentinel --pool-id pool_pilotos_sentinel \
  --max-seats 500 --expiry 2026-10-21T00:00:00Z \
  --out backend/scripts/license_out/itv-examen-500.lic
```

- La `.lic` emitida se monta como `/app/config/licenses/client.lic` (con
  `SENTINEL_ALLOW_DEV_LICENSE=true`, ya en `client.env`). **Guardala FUERA del repo.**
- **Nunca** `issue_dev_license.py` sobre un stack vivo: regenera el keyset (footgun
  documentado — invalida toda licencia en caliente).
- Instalá la licencia definitiva **antes** de seedear: ampliar en caliente son ~5 min de
  402 intermitentes. El pre-check del seeder falla-rápido si la licencia no alcanza.

### Caveat de tenant en el pre-check (límite del producto, no del seeder)

El pre-check de seats del seeder lee `GET /api/v1/health/license`, que cuenta los seats
del `expected_tenant_id()` (`SENTINEL_DEPLOYMENT_TENANT_ID`), mientras que el seat gate real de
`keys.py` cuenta contra `DEFAULT_TENANT_ID` hasta que la 013 resuelva tenant en los
handlers. Si ambos difirieran, el `seats_used` del pre-check podría contar otro tenant que
el que el gate enforcea. Por eso `client.env` fija
`SENTINEL_DEPLOYMENT_TENANT_ID=00000000-0000-0000-0000-000000000001` (= DEFAULT): con eso
coinciden y el pre-check es fiel. **No cambies ese tenant** sin entender esta relación.
El enforcement real sigue siendo el 402 del backend (el seeder lo trata como fail-fast).
