# Task-runner de la 020 (T003): build de imágenes prod + validación de artefactos.
# Los checks son la "suite de tests" de esta spec: exit != 0 = rojo.

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
BACKEND_IMG ?= basa-backend:prod
FRONTEND_IMG ?= basa-frontend:prod
DOCS_IMG ?= basa-docs:prod
# Marca por defecto para el entregable de la extensión (028): el piloto Cámara.
EXT_BRAND ?= camara-comercio

.PHONY: build build-backend build-frontend build-docs build-docs-brand build-extension-brand docs-refs check check-images check-whitelabel check-extension-whitelabel check-secrets check-tofu check-docs check-trust-kit check-engine-admission check-engine-local-limits

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
		--build-arg DOCS_VERSION=$(VERSION) -t basa-docs:$(BRAND)-$(VERSION) $(REPO_ROOT)/docs

# Entregable white-label de la EXTENSIÓN de navegador (028 US1): renderiza el zip
# con la marca del partner desde deploy/clients/$(BRAND)/brand.extension.json.
# Uso: make build-extension-brand BRAND=camara-comercio
build-extension-brand:
	test -n "$(BRAND)" || { echo "uso: make build-extension-brand BRAND=<slug>"; exit 1; }
	$(REPO_ROOT)/deploy/release/render_extension_brand.sh $(BRAND) \
		$(REPO_ROOT)/deploy/clients/$(BRAND)/brand.extension.json

check: check-images check-whitelabel check-extension-whitelabel check-secrets check-tofu check-docs check-trust-kit check-redis-wiring check-engine-admission check-engine-local-limits

# Regenera los references single-source del sitio (022 US5): OpenAPI + config/env.
docs-refs:
	cd $(REPO_ROOT) && docker compose run --rm --no-deps -e BRAND_NAME="AI Gateway" backend \
		python scripts/export_openapi.py 2>/dev/null > docs/docs/api-reference/openapi.json.tmp \
		&& mv docs/docs/api-reference/openapi.json.tmp docs/docs/api-reference/openapi.json
	cd $(REPO_ROOT) && python3 docs/gen_config_reference.py

check-images:
	BACKEND_IMG=$(BACKEND_IMG) $(REPO_ROOT)/deploy/release/checks/test_backend_image.sh
	FRONTEND_IMG=$(FRONTEND_IMG) $(REPO_ROOT)/deploy/release/checks/test_frontend_image.sh

# build-docs primero: sin la dependencia, los checks de imagen validaban la ÚLTIMA
# imagen buildeada (potencialmente stale) y el gate quedaba verde con docs viejas
# (descubierto 2026-07-21: el preview servía contenido sin las superficies nuevas
# mientras el gate reportaba ✅).
check-docs: build-docs
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_image.sh
	$(REPO_ROOT)/deploy/release/checks/test_docs_strict_build.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_content.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_neutral_naming.sh
	$(REPO_ROOT)/deploy/release/checks/test_docs_whitelabel.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_search_offline.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_apiref.sh
	$(REPO_ROOT)/deploy/release/checks/test_docs_structure.sh
	DOCS_IMG=$(DOCS_IMG) $(REPO_ROOT)/deploy/release/checks/test_docs_versioning.sh

check-whitelabel:
	$(REPO_ROOT)/deploy/release/checks/test_no_engine_name.sh

# Gate white-label de la EXTENSIÓN (028 US7): renderiza el zip del partner y verifica
# que no re-filtre la marca del fabricante ni el motor (allowlist interna respetada).
# Fuente única de la marca: deploy/clients/$(EXT_BRAND)/brand.extension.json.
check-extension-whitelabel:
	$(REPO_ROOT)/deploy/release/render_extension_brand.sh $(EXT_BRAND) \
		$(REPO_ROOT)/deploy/clients/$(EXT_BRAND)/brand.extension.json
	$(REPO_ROOT)/deploy/release/checks/test_extension_whitelabel.sh $(EXT_BRAND)

check-secrets:
	$(REPO_ROOT)/deploy/release/checks/test_no_default_secrets.sh

# costura → Falime (Factory): backend y motor escriben/leen las MISMAS claves de Redis
# (`basa:audit:*` de la 031, `basa:nlp:*` del #63). Si el perfil no le cablea REDIS_HOST al
# motor —o los defaults del código divergen—, el health cuenta cero mientras el otro plano
# registra: la degradación vuelve a ser silenciosa sin ningún síntoma visible.
check-redis-wiring:
	$(REPO_ROOT)/deploy/release/checks/test_redis_wiring.sh

# nodo C1 (issue #151): las perillas de admisión al motor son env-tuneables en el CÓDIGO,
# pero una instalación sólo las puede girar si el perfil se las cablea. Invariante de
# despliegue, igual que el de Redis — y por el mismo motivo vive acá y no en pytest: el
# contenedor de la suite no monta la raíz del repo, así que no ve ningún compose.
check-engine-admission:
	$(REPO_ROOT)/deploy/release/checks/test_engine_admission_wiring.sh

# nodo C1 (issue #151): límites del motor sobre el runtime local —techo de paralelismo y
# reintentos en 0 (#134-②)— en TODO catálogo que lo use, incluidas las plantillas de perfil
# que el contract test del backend no puede ver desde su contenedor. Más un contract test
# VIVO contra la imagen pinneada: los dos valores viajan como parámetros del deployment y
# nadie garantiza desde el YAML que se conviertan en un semáforo y en un solo intento.
check-engine-local-limits:
	$(REPO_ROOT)/deploy/release/checks/test_engine_local_limits.sh

# Kit de confianza del certificado (issue #51): el .ps1 parsea de verdad, la codificación
# no rompe en la ventana del cliente y el bundle se lo lleva. Los pasos que exigen Windows
# (UAC, almacén de máquina, registro de Firefox) quedan para una VM real.
check-trust-kit:
	$(REPO_ROOT)/deploy/release/checks/test_trust_kit.sh

check-tofu:
	$(REPO_ROOT)/deploy/release/checks/test_tofu_validate.sh
