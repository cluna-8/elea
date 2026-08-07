# Quickstart — validación viva de la 026 (`basa-admin-signer` + `basa-admin`)

Escenarios ejecutables que prueban el MVP end-to-end en **dos artefactos físicamente
separados** (spec.md § Clarifications — Session 2026-08-05; FR-016 a FR-023).
Prerrequisitos: repo en main con la 026 implementada, Docker arriba, Python 3.11+ en el
host (prerrequisito documentado del partner).

```bash
# 0) Build de AMBOS artefactos (.pyz por paquete, en contenedor — no exige nada al host)
make -C cli build-signer                     # single-arch, estación de firma de Basa
make -C cli build-admin                      # por arquitectura x86_64/arm64
ls cli/basa_admin_signer/dist/basa-admin-signer-*.pyz
ls cli/basa_admin/dist/basa-admin-*.pyz

# 1) SEPARACIÓN FÍSICA (FR-020, build time, obligatoria antes de distribuir nada):
#    contract test del signer + test de inspección de artefacto del admin
make -C cli test-contract-signer
#    → pytest cli/basa_admin_signer/tests/ (unit + CliRunner) Y el e2e:
#      el .pyz emite un .lic → docker compose run backend valida con verify_license_blob
make -C cli test-artifact-boundary-admin
#    → abre basa-admin-*.pyz (zipfile) y FALLA el build si aparece cualquier módulo/
#      símbolo/dependencia exclusivo del signer (keycustody/signing/ledger de emisiones)

# 2) Emitir una licencia dev por flags — SOLO con basa-admin-signer,
#    en la estación de firma (sin editar código, sin tocar el keyset)
KEYSET_ANTES=$(sha256sum backend/src/keys/basa_public_keys.pem)
./cli/basa_admin_signer/dist/basa-admin-signer-*.pyz license issue-dev \
    --tenant <TENANT_ID> --seats 10 --expiry 2027-01-01 --out /tmp/demo.lic  # passphrase por prompt
sha256sum backend/src/keys/basa_public_keys.pem      # DEBE ser == $KEYSET_ANTES (SC-002)

# 3) Verificación offline del .lic (ambos artefactos exponen `license verify`,
#    solo verificación pública — ver research.md D6) + verificación en el producto vivo
./cli/basa_admin_signer/dist/basa-admin-signer-*.pyz license verify /tmp/demo.lic
docker compose run --rm --no-deps backend python -c \
  "from src.licensing.verifier import verify_license_blob, BasaPublicKeySet; \
   print(verify_license_blob(open('/tmp/demo.lic').read(), \
     BasaPublicKeySet.from_pem_file('src/keys/basa_public_keys.pem')).license_id)"

# 4) Secuencia de instalación guiada contra el stack dev (SC-001) —
#    SOLO con basa-admin, en el host del partner/cliente. El .lic firmado en (2)
#    viaja como ARCHIVO fuera de banda hasta acá (nunca basa-admin-signer).
basa-admin install profile render <slug>        # valida layout + vars, error legible
basa-admin install seed apply --dry-run ...     # muestra diff (incl. rename tenant), no commitea
basa-admin install seed apply ...               # confirma mostrando a qué DB apunta; keys a archivo 600
basa-admin install license verify /tmp/demo.lic # sanity offline previo a instalar
basa-admin install license install /tmp/demo.lic   # puebla el volumen + restart + poll /health/license
basa-admin install admin bootstrap --username admin   # password por prompt (SC-004; mata el TOFU raceable)
basa-admin install verify <slug>                # smoke e2e en verde (licencia activa + gateway + masking)

# 5) Garantía offline (SC-005): la suite del núcleo de AMBOS artefactos corre con la red cortada
make -C cli test-offline-signer   # pytest en contenedor con --network none + check de imports prohibidos
make -C cli test-offline-admin    # ídem, paquete basa_admin

# 6) Bundle air-gapped: layout completo de FR-021, SOLO basa-admin viaja adentro — basa-admin-signer NUNCA
basa-admin install bundle create <slug> --from-lockfile release.lock --out /tmp/bundle
tar -tzf /tmp/bundle/bundle-v*.tar.gz > /tmp/bundle_listing.txt
grep -E '^bin/' /tmp/bundle_listing.txt
#    → esperado EXACTAMENTE: bin/basa-admin-x86_64.pyz, bin/basa-admin-arm64.pyz
grep -qE '^images/' /tmp/bundle_listing.txt
grep -qE '^manifests/' /tmp/bundle_listing.txt
grep -qE '^profiles/' /tmp/bundle_listing.txt
grep -qx 'install.sh' /tmp/bundle_listing.txt
#    → los 5 top-level de FR-021 se verifican por SEPARADO, no con un OR: bin/, images/,
#      manifests/, profiles/ e install.sh deben existir TODOS (si falta cualquiera de los
#      tres directorios, la línea correspondiente falla sola — no basta con que aparezca
#      uno solo de los tres)
! grep -q 'basa-admin-signer' /tmp/bundle_listing.txt
#    → escaneo del tarball COMPLETO (no solo bin/): si aparece basa-admin-signer en
#      CUALQUIER ruta, el build está roto — FR-021/FR-023

# 7) Instalar basa-admin en un host limpio usando SOLO install.sh (FR-023: nunca pip/apt/yum)
rm -rf /tmp/bundle-extracted && mkdir -p /tmp/bundle-extracted
#    → extracción limpia: sin restos de una corrida anterior
tar -xzf /tmp/bundle/bundle-v*.tar.gz -C /tmp/bundle-extracted
test -x /tmp/bundle-extracted/install.sh
#    → NO se invoca como `sh install.sh` (eso ignora el bit +x); esta aserción falla si
#      `bundle create` (T033) no dejó install.sh ejecutable dentro del tarball
/tmp/bundle-extracted/install.sh
#    → ejecutado directamente (./install.sh vía ruta absoluta), ejercitando el bit +x
#      real; copia el .pyz de la arquitectura detectada, fija permisos ejecutables; cero
#      red, cero pip/apt/yum (FR-023)
```

**Resultados esperados**: (1) ambos artefactos buildean y pasan su gate de separación
física; (2) keyset intacto tras emitir con `basa-admin-signer`; (3) el mismo `.lic` valida
en ambos artefactos y en el producto; (4) instalación completa con `basa-admin` sin editar
scripts ni SQL, con confirmaciones visibles, sin haber tocado `basa-admin-signer`; (5)
núcleo de ambos verificado sin red; (6) el bundle tiene el layout completo de FR-021 y
solo contiene `basa-admin` en cualquier ruta; (7) `install.sh` deja `basa-admin` listo
para usar sin pip/apt/yum ni red.

Detalle de garantías por comando: [contracts/cli-comandos.md](contracts/cli-comandos.md).
Modelo de artefactos y separación física: [data-model.md](data-model.md),
[research.md](research.md) D6.
