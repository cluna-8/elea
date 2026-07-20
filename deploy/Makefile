# Task-runner de la 020 (T003): build de imágenes prod + validación de artefactos.
# Los checks son la "suite de tests" de esta spec: exit != 0 = rojo.

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
BACKEND_IMG ?= basa-backend:prod
FRONTEND_IMG ?= basa-frontend:prod

.PHONY: build build-backend build-frontend check check-images check-whitelabel check-secrets check-tofu

build: build-backend build-frontend

build-backend:
	docker build -f $(REPO_ROOT)/deploy/docker/backend.prod.Dockerfile -t $(BACKEND_IMG) $(REPO_ROOT)

build-frontend:
	docker build -f $(REPO_ROOT)/deploy/docker/frontend.prod.Dockerfile -t $(FRONTEND_IMG) $(REPO_ROOT)

check: check-images check-whitelabel check-secrets check-tofu

check-images:
	BACKEND_IMG=$(BACKEND_IMG) $(REPO_ROOT)/deploy/release/checks/test_backend_image.sh
	FRONTEND_IMG=$(FRONTEND_IMG) $(REPO_ROOT)/deploy/release/checks/test_frontend_image.sh

check-whitelabel:
	$(REPO_ROOT)/deploy/release/checks/test_no_engine_name.sh

check-secrets:
	$(REPO_ROOT)/deploy/release/checks/test_no_default_secrets.sh

check-tofu:
	$(REPO_ROOT)/deploy/release/checks/test_tofu_validate.sh
