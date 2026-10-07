"""Entrega de la capa 2 (T018/T022, research D21): cableado en los archivos propios de Sentinel.

Sin Docker: se fija el contrato de los scripts (qué copian, qué aplican y cuándo) y que la
extensión NO se active sola por el mero hecho de estar desplegada.
"""
import re
import subprocess
from pathlib import Path

import pytest

import yaml

ROOT = Path(__file__).resolve().parents[3]

if not (ROOT / "deploy/clients/nix").exists():
    pytest.skip("Despliegue nix de Sentinel (deploy/clients/nix/**): no existe en Eleia, que entrega la extension por S9/S11 (T020, test_extension_delivery.sh) y las variantes -ext (T091, test_ext_images.sh). 057 T017",
                allow_module_level=True)
DEPLOY = (ROOT / "deploy/clients/nix/host/deploy.sh").read_text()
ROLLBACK = (ROOT / "deploy/clients/nix/host/rollback.sh").read_text()
RELEASE = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
DOCKERFILE = (ROOT / "sentinel/docker/backend.Dockerfile").read_text()


def _steps(job):
    return "\n".join(s.get("run", "") for s in RELEASE["jobs"][job]["steps"])


def test_scripts_parsean():
    for f in ("deploy.sh", "rollback.sh"):
        subprocess.run(["bash", "-n", str(ROOT / "deploy/clients/nix/host" / f)], check=True)


def test_compose_recibe_el_entorno_extra_por_interpolacion_en_deploy_y_rollback():
    for txt in (DEPLOY, ROLLBACK):
        assert "EXTRA_ENV_FILE=/dev/null" in txt              # sin archivo: nada cambia
        assert "extensions.interp.env" in txt
        assert "env EXTRA_ENV_FILE" not in txt                 # por interpolación, no por `sudo env`
    compose_fn = DEPLOY[DEPLOY.index("compose() {"):]
    compose_fn = compose_fn[:compose_fn.index("\n}")]
    assert '--env-file "$INTERP"' in compose_fn


def test_fragmento_y_guard_solo_con_la_redireccion_activada():
    block = DEPLOY[DEPLOY.index('if [ "$REDIRECT_ON" = 1 ]; then'):]
    block = block[:block.index("\nfi\n")]
    assert "fragment_merge.py" in block and "profile-fragment.yaml" in block
    assert "cp /sentinel/redirect_*.py /vol/extensions/" in block
    assert re.search(r"GATEWAY_PLUGINS=\.\*sentinel\\\\?\.redirect\\\\?\.plugin", DEPLOY)
    # la fusión corre sobre el config RECIÉN renderizado del template (nunca dos veces)
    assert DEPLOY.index("config.yaml con variables sin resolver") < DEPLOY.index("fragment_merge.py")


def test_el_release_sube_la_capa_2_del_motor_y_hornea_la_del_backend():
    deploy_steps = _steps("deploy-nix")
    assert "sentinel/engine/ nix:sentinel-deploy/release/sentinel-engine/" in deploy_steps
    build = _steps("build-publish")
    assert "sentinel/docker/backend.Dockerfile" in build
    assert build.index("deploy/release/publish.sh") < build.index("sentinel/docker/backend.Dockerfile")


def test_la_imagen_derivada_solo_hornea_codigo():
    for d in ("sentinel/redirect", "sentinel/onboarding", "sentinel/engine", "sentinel/migrations"):
        assert f"COPY {d} " in DOCKERFILE
    assert "sentinel/tests" not in DOCKERFILE
    assert "ENV PYTHONPATH=/opt/sentinel-ext" in DOCKERFILE
    for var in ("GATEWAY_PLUGINS", "PLUGIN_PACKAGES", "ALEMBIC_EXTRA_VERSION_LOCATIONS",
                "REDIRECT_INTERNAL_KEY"):
        assert not re.search(rf"^ENV .*{var}", DOCKERFILE, flags=re.M), var
    assert DOCKERFILE.rstrip().endswith("USER sentinel")


def test_la_imagen_hornea_la_siembra_del_wizard_y_su_migracion_070():
    """El instalador ejecuta `python -m sentinel.onboarding.apply_wizard_profile` dentro del backend."""
    assert "COPY sentinel/onboarding /opt/sentinel-ext/sentinel/onboarding" in DOCKERFILE
    assert (ROOT / "sentinel/onboarding/apply_wizard_profile.py").exists()
    assert list((ROOT / "sentinel/migrations").glob("*_wizard_profile.py"))


# ── catálogo de modelos (069): migración y siembra con el backend sano, solo si está montado ──

def test_catalogo_solo_si_el_entorno_de_extensiones_monta_su_api():
    assert re.search(r"PLUGIN_PACKAGES=\.\*sentinel\\\.catalog\\\.api", DEPLOY)
    block = DEPLOY[DEPLOY.index('if [ "$CATALOG_ON" = 1 ]; then'):]
    block = block[:block.index("\nfi\n\n")]
    assert "sentinel.catalog.migrate" in block and "sentinel.catalog.seed" in block
    assert "catalog-seed.yaml" in block


def test_el_paso_del_catalogo_corre_con_el_backend_sano_y_no_tumba_el_deploy():
    sano = DEPLOY.index('[ "$st" = healthy ] || {')
    paso = DEPLOY.index('if [ "$CATALOG_ON" = 1 ]; then')
    smoke = DEPLOY.index('bash "$DEPLOY/host/smoke.sh"')
    assert sano < paso < smoke
    # Solo el bloque del catálogo: entre él y el smoke hay otros pasos con su propio `|| log`
    # (la descarga del modelo del generador, ADAPT-033).
    block = DEPLOY[paso:smoke]
    block = block[:block.index("\nfi\n") + len("\nfi\n")]
    assert block.count("|| log") == 2 and "die " not in block


def test_la_descarga_del_modelo_del_generador_corre_con_el_backend_sano_y_no_tumba_el_deploy():
    sano = DEPLOY.index('[ "$st" = healthy ] || {')
    paso = DEPLOY.index('host/pull-modelo-generador.sh')
    smoke = DEPLOY.index('bash "$DEPLOY/host/smoke.sh"')
    assert sano < paso < smoke
    linea = DEPLOY[paso:DEPLOY.index("\n", DEPLOY.index("\n", paso) + 1)]
    assert "|| log" in linea and "die " not in linea


def test_la_semilla_viaja_con_el_release():
    assert "catalog-seed.yaml nix:sentinel-deploy/release/" in _steps("deploy-nix")


# ── las imágenes llevan TODO lo que el código importa (el release del 1-oct falló por esto) ──

def test_la_imagen_del_backend_copia_cada_paquete_de_la_extension():
    backend = (ROOT / "sentinel/docker/backend.Dockerfile").read_text()
    paquetes = [d.name for d in (ROOT / "sentinel").iterdir()
                if d.is_dir() and (d / "__init__.py").exists() and d.name != "tests"]
    assert {"redirect", "catalog", "common", "onboarding"} <= set(paquetes)
    for nombre in paquetes:
        assert f"COPY sentinel/{nombre} /opt/sentinel-ext/sentinel/{nombre}" in backend, nombre
    assert "COPY sentinel/migrations /opt/sentinel-ext/sentinel/migrations" in backend


def test_la_imagen_del_frontend_copia_cada_carpeta_que_importan_las_paginas():
    dockerfile = (ROOT / "sentinel/docker/frontend.Dockerfile").read_text()
    pages = ROOT / "sentinel/frontend/pages"
    carpetas = set()
    for f in pages.glob("*.tsx"):
        carpetas |= set(re.findall(r'from "\.\./([a-z]+)/', f.read_text()))
    assert {"models"} <= carpetas
    for c in carpetas:
        assert f"COPY sentinel/frontend/{c} /build/sentinel/frontend/{c}" in dockerfile, c
    assert "catalog/__tests__" in dockerfile and "redirect/__tests__" in dockerfile


def test_la_068_tolera_una_imagen_sin_el_paquete_del_catalogo(monkeypatch):
    import builtins
    import sys
    real = builtins.__import__

    def sin_catalogo(name, *a, **k):
        if name.startswith("sentinel.catalog"):
            raise ImportError("sin catálogo")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sin_catalogo)
    for mod in [m for m in sys.modules if m.startswith("sentinel.catalog")]:
        monkeypatch.delitem(sys.modules, mod)
    from sentinel.redirect.store import _overlay_catalog
    d, o, c = {"a": 1}, (), {}
    assert _overlay_catalog(None, "t", d, o, c) == (d, o, c)


# ── fuente única (069 US7, T146): con CATALOG_ONLY no se rescatan modelos de consola ──

def _bloque_rescate():
    ini = DEPLOY.index('if [ "$CATALOG_ONLY_ON" = 1 ]; then')
    return DEPLOY[ini:DEPLOY.index('rm -f "$STATE/config.yaml.vivo"')]


def test_catalog_only_se_detecta_en_el_archivo_de_extensiones():
    assert re.search(r"CATALOG_ONLY_ON=0\ngrep .*CATALOG_ONLY=\(1\|true\|yes\).*\$EXTRA_ENV_FILE", DEPLOY)


def test_con_el_flag_no_corre_el_rescate_y_sin_el_flag_si():
    antes, despues = _bloque_rescate().split("\nelse\n", 1)
    assert "conservar_modelos_consola.py" not in antes
    assert "conservar_modelos_consola.py" in despues
    # el script y su test siguen: se retiran en una etapa posterior, con el flag probado
    assert (ROOT / "deploy/clients/nix/host/conservar_modelos_consola.py").exists()
    assert (ROOT / "sentinel/tests/unit/test_conservar_modelos_consola.py").exists()


def test_los_marcadores_que_la_imagen_busca_en_el_build_existen_en_el_codigo():
    """El `RUN npx vite build && grep -q "<texto>" …` del Dockerfile del frontend falla el release si el texto
    cambia (pasó el 2-oct con «Routing por costo»). Cada marcador debe seguir existiendo en las fuentes."""
    dockerfile = (ROOT / "sentinel/docker/frontend.Dockerfile").read_text()
    marcadores = re.findall(r'grep -q "([^"]+)" dist/assets', dockerfile)
    assert len(marcadores) >= 2
    fuentes = "\n".join(p.read_text(errors="ignore") for p in (ROOT / "sentinel/frontend").rglob("*.tsx")
                        if "__tests__" not in p.parts)
    for m in marcadores:
        assert m in fuentes, f"el marcador {m!r} ya no existe en sentinel/frontend: el build de la imagen fallaría"
