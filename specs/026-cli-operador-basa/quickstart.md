# Quickstart — validación viva de la 026 (`basa-admin`)

Escenarios ejecutables que prueban el MVP end-to-end. Prerrequisitos: repo en main con
la 026 implementada, Docker arriba. **No requiere Go en el host** (el build corre en
contenedor; ver plan.md).

```bash
# 0) Build del binario (en contenedor golang; produce cli/dist/basa-admin-<os>-<arch>)
make -C cli build

# 1) CONTRATO CROSS-LENGUAJE (el corazón del riesgo): los golden vectors
#    firmados desde Go DEBEN validar en el verifier Python, y viceversa.
make -C cli test-contract
#    → corre go test ./... (golden vectors) Y
#      docker compose run --rm --no-deps backend pytest tests/contract/test_lic_cross_language.py -q

# 2) Emitir una licencia dev por flags (sin editar código, sin tocar el keyset)
KEYSET_ANTES=$(sha256sum backend/src/keys/basa_public_keys.pem)
./cli/dist/basa-admin license issue-dev --tenant <TENANT_ID> --seats 10 \
    --expiry 2027-01-01 --out /tmp/demo.lic
sha256sum backend/src/keys/basa_public_keys.pem   # DEBE ser == $KEYSET_ANTES (SC-002)

# 3) Verificación offline del .lic (Go) + verificación cruzada (Python)
./cli/dist/basa-admin license verify /tmp/demo.lic
docker compose run --rm --no-deps backend python -c \
  "from src.licensing.verifier import verify_license_blob, BasaPublicKeySet; \
   print(verify_license_blob(open('/tmp/demo.lic').read(), \
     BasaPublicKeySet.from_pem_file('src/keys/basa_public_keys.pem')).license_id)"

# 4) Secuencia de instalación guiada contra el stack dev (SC-001)
./cli/dist/basa-admin install profile render <slug>       # valida layout + vars
./cli/dist/basa-admin install seed apply --dry-run ...    # muestra diff, no commitea
./cli/dist/basa-admin install seed apply ...              # pide confirmación, keys a archivo 600
./cli/dist/basa-admin install license install /tmp/demo.lic
./cli/dist/basa-admin install admin bootstrap --username admin   # password por prompt (SC-004)
./cli/dist/basa-admin install verify <slug>               # smoke e2e en verde

# 5) Garantía offline (SC-005): la suite del núcleo corre con la red cortada
make -C cli test-offline   # go test con red bloqueada (sin sockets salientes)
```

**Resultados esperados**: (1) contrato verde en ambas direcciones; (2) keyset intacto
tras emitir; (3) el mismo `.lic` valida en Go y Python; (4) instalación completa sin
editar scripts ni SQL, con confirmaciones visibles; (5) núcleo verificado sin red.

Detalle de garantías por comando: [contracts/cli-comandos.md](contracts/cli-comandos.md).
Modelo de artefactos: [data-model.md](data-model.md).
