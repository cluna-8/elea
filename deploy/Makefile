# Task-runner de la 020 (T003): build de imágenes prod + validación de artefactos.
# Los checks son la "suite de tests" de esta spec: exit != 0 = rojo.

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
BACKEND_IMG ?= basa-backend:prod
FRONTEND_IMG ?= basa-frontend:prod
DOCS_IMG ?= basa-docs:prod

.PHONY: build build-backend build-frontend build-docs check check-images check-whitelabel check-secrets check-tofu check-docs

build: build-backend build-frontend build-docs

build-backend:
	docker build -f $(REPO_ROOT)/deploy/docker/backend.prod.Dockerfile -t $(BACKEND_IMG) $(REPO_ROOT)

build-frontend:
	docker build -f $(REPO_ROOT)/deploy/docker/frontend.prod.Dockerfile -t $(FRONTEND_IMG) $(REPO_ROOT)

# El Dockerfile del sitio vive junto al contenido (docs/), no en deploy/docker/:
# el contexto de build ES el sitio (022 US1).
build-docs:
	docker build -f $(REPO_ROOT)/docs/Dockerfile -t $(DOCS_IMG) $(REPO_ROOT)/docs

# Imagen POR MARCA (022 US3, FR-012): antes correr
#   deploy/release/render_docs_brand.sh $(BRAND) <brand.json>   (deriva del pack 020)
# Uso: make build-docs-brand BRAND=aegis VERSION=1.0
build-docs-brand:
	test -n "$(BRAND)" -a -n "$(VERSION)" || { echo "uso: make build-docs-brand BRAND=<slug> VERSION=<v>"; exit 1; }
	docker build -f $(REPO_ROOT)/docs/Dockerfile --build-arg BRAND=$(BRAND) \
		-t basa-docs:$(BRAND)-$(VERSION) $(REPO_ROOT)/docs

check: check-images check-whitelabel check-secrets check-tofu check-docs

check-images:
	BACKEND_IMG=$(BACKEND_IMG) $(REPO_ROOT)/deploy/release/checks/test_backend_image.sh
	FRONTEND_IMG=$(FRONTEND_IMG) $(REPO_ROOT)/deploy/release/checks/test_frontend_image.sh

check-docs:
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_image.sh
	$(REPO_ROOT)/deploy/release/checks/test_docs_strict_build.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_content.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_neutral_naming.sh
	$(REPO_ROOT)/deploy/release/checks/test_docs_whitelabel.sh

check-whitelabel:
	$(REPO_ROOT)/deploy/release/checks/test_no_engine_name.sh

check-secrets:
	$(REPO_ROOT)/deploy/release/checks/test_no_default_secrets.sh

check-tofu:
	$(REPO_ROOT)/deploy/release/checks/test_tofu_validate.sh
