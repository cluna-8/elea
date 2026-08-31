# 026 T004 — build .pyz por arquitectura (shiv) + targets de test de sentinel-admin.
# Requiere `pip install -e ".[dev]"` en este directorio. build-x86_64/build-arm64
# bajan wheels de cryptography por plataforma (research.md D3) - se corren en la
# maquina de build/CI del partner, nunca en la caja airgapped.
SHIV_ROOT ?= $(HOME)/.cache/sentinel-admin/shiv
DIST := dist

.PHONY: build-x86_64 build-arm64 test test-offline test-artifact-boundary test-bundle-contents clean

build-x86_64:
	mkdir -p $(DIST)
	SHIV_ROOT=$(SHIV_ROOT) shiv -c sentinel-admin -p '/usr/bin/env python3' \
		--platform manylinux2014_x86_64 --python-version 311 --only-binary=:all: \
		-o $(DIST)/sentinel-admin-x86_64.pyz .

build-arm64:
	mkdir -p $(DIST)
	SHIV_ROOT=$(SHIV_ROOT) shiv -c sentinel-admin -p '/usr/bin/env python3' \
		--platform manylinux2014_aarch64 --python-version 311 --only-binary=:all: \
		-o $(DIST)/sentinel-admin-arm64.pyz .

test:
	pytest tests/ -q

# Pendiente: 026 Fase 2 (T014) agrega el check de imports prohibidos + marker de
# red cortada. No hay nada que correr todavia en este bloque (T001-T005).
test-offline:
	@echo "sentinel-admin/test-offline: pendiente (026 Fase 2, T014) - nada que correr en este bloque"

# Pendiente: 026 Fase 5 (T031/T034) agrega la inspeccion del .pyz contra el
# signer + el grep anti-runtime-gating. No hay nada que correr todavia.
test-artifact-boundary:
	@echo "sentinel-admin/test-artifact-boundary: pendiente (026 Fase 5, T031/T034) - nada que correr en este bloque"

# Pendiente: 026 Fase 5 (T032/T033) agrega la verificacion de layout+MANIFEST
# del bundle air-gapped. No hay nada que correr todavia.
test-bundle-contents:
	@echo "sentinel-admin/test-bundle-contents: pendiente (026 Fase 5, T032/T033) - nada que correr en este bloque"

clean:
	rm -rf $(DIST) build *.egg-info
