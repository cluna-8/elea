# Quickstart — validación viva de la 026 (`basa-admin`)

Escenarios ejecutables que prueban el MVP end-to-end. Prerrequisitos: repo en main con
la 026 implementada, Docker arriba, Python 3.11+ en el host (prerrequisito documentado
del partner).

```bash
# 0) Build del artefacto (.pyz por arquitectura, en contenedor — no exige nada al host)
make -C cli build
ls cli/dist/basa-admin-*.pyz

# 1) CONTRATO DEL ARTEFACTO: lo que el .pyz firma lo valida el backend del producto
#    (mismo código de licensing, pero el test cubre el EMPAQUETADO)
make -C cli test-contract
#    → pytest cli/tests/ (unit + CliRunner) Y el e2e:
#      el .pyz emite un .lic → docker compose run backend valida con verify_license_blob

# 2) Emitir una licencia dev por flags (sin editar código, sin tocar el keyset)
KEYSET_ANTES=$(sha256sum backend/src/keys/basa_public_keys.pem)
./cli/dist/basa-admin-*.pyz license issue-dev --tenant <TENANT_ID> --seats 10 \
    --expiry 2027-01-01 --out /tmp/demo.lic          # passphrase por prompt
sha256sum backend/src/keys/basa_public_keys.pem      # DEBE ser == $KEYSET_ANTES (SC-002)

# 3) Verificación offline del .lic + verificación en el producto vivo
./cli/dist/basa-admin-*.pyz license verify /tmp/demo.lic
docker compose run --rm --no-deps backend python -c \
  "from src.licensing.verifier import verify_license_blob, BasaPublicKeySet; \
   print(verify_license_blob(open('/tmp/demo.lic').read(), \
     BasaPublicKeySet.from_pem_file('src/keys/basa_public_keys.pem')).license_id)"

# 4) Secuencia de instalación guiada contra el stack dev (SC-001)
basa-admin install profile render <slug>        # valida layout + vars, error legible
basa-admin install seed apply --dry-run ...     # muestra diff (incl. rename tenant), no commitea
basa-admin install seed apply ...               # confirma mostrando a qué DB apunta; keys a archivo 600
basa-admin install license install /tmp/demo.lic   # puebla el volumen + restart + poll /health/license
basa-admin install admin bootstrap --username admin   # password por prompt (SC-004; mata el TOFU raceable)
basa-admin install verify <slug>                # smoke e2e en verde (licencia activa + gateway + masking)

# 5) Garantía offline (SC-005): la suite del núcleo corre con la red cortada
make -C cli test-offline   # pytest en contenedor con --network none + check de imports prohibidos
```

**Resultados esperados**: (1) contrato del artefacto verde; (2) keyset intacto tras
emitir; (3) el mismo `.lic` valida en la CLI y en el producto; (4) instalación completa
sin editar scripts ni SQL, con confirmaciones visibles; (5) núcleo verificado sin red.

Detalle de garantías por comando: [contracts/cli-comandos.md](contracts/cli-comandos.md).
Modelo de artefactos: [data-model.md](data-model.md).
