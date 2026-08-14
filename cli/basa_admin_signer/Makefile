# 026 T003 — build .pyz (shiv, single-arch, estacion de firma) + targets de test
# de basa-admin-signer. Requiere `pip install -e ".[dev]"` en este directorio.
SHIV_ROOT ?= $(HOME)/.cache/basa-admin-signer/shiv
DIST := dist
PYZ := $(DIST)/basa-admin-signer.pyz

.PHONY: build test test-offline test-contract clean

build:
	mkdir -p $(DIST)
	SHIV_ROOT=$(SHIV_ROOT) shiv -c basa-admin-signer -o $(PYZ) .

test:
	pytest tests/ -q

# Pendiente: 026 Fase 2 (T013) agrega el check de imports prohibidos + marker de
# red cortada. No hay nada que correr todavia en este bloque (T001-T005).
test-offline:
	@echo "basa-admin-signer/test-offline: pendiente (026 Fase 2, T013) - nada que correr en este bloque"

# Pendiente: 026 Fase 3 (T019) agrega el contract test del artefacto (.pyz firma
# -> el backend valida). No hay nada que correr todavia en este bloque.
test-contract:
	@echo "basa-admin-signer/test-contract: pendiente (026 Fase 3, T019) - nada que correr en este bloque"

clean:
	rm -rf $(DIST) build *.egg-info
