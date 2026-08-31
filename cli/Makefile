# 026 T005 — orquesta los dos paquetes de cli/ (sentinel_admin_signer, sentinel_admin).
# Cada sub-Makefile (sentinel_admin_signer/Makefile, sentinel_admin/Makefile - T003/T004)
# es quien sabe construir/testear su propio paquete; este archivo solo delega.
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
SIGNER := $(REPO_ROOT)/cli/sentinel_admin_signer
ADMIN := $(REPO_ROOT)/cli/sentinel_admin

.PHONY: build-signer build-admin test test-boundary \
	test-contract-signer test-offline-signer test-offline-admin \
	test-artifact-boundary-admin test-bundle-contents-admin clean

build-signer:
	$(MAKE) -C $(SIGNER) build

build-admin:
	$(MAKE) -C $(ADMIN) build-x86_64
	$(MAKE) -C $(ADMIN) build-arm64

# Test transversal (FR-016): ningun pyproject.toml cruza hacia el paquete hermano.
test-boundary:
	pytest $(REPO_ROOT)/cli/tests/ -q

test: test-boundary
	$(MAKE) -C $(SIGNER) test
	$(MAKE) -C $(ADMIN) test

test-contract-signer:
	$(MAKE) -C $(SIGNER) test-contract

test-offline-signer:
	$(MAKE) -C $(SIGNER) test-offline

test-offline-admin:
	$(MAKE) -C $(ADMIN) test-offline

test-artifact-boundary-admin:
	$(MAKE) -C $(ADMIN) test-artifact-boundary

test-bundle-contents-admin:
	$(MAKE) -C $(ADMIN) test-bundle-contents

clean:
	$(MAKE) -C $(SIGNER) clean
	$(MAKE) -C $(ADMIN) clean
