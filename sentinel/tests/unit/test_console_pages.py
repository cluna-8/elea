"""Pantalla de consola de la 068 (costura S3): el catálogo del frontend espeja los enums del
backend, y el build de la imagen del frontend toma las páginas de capa 2.

Sin Node ni Docker: se lee el TypeScript como texto. Si el backend suma un proveedor o cambia
la forma de una credencial, este test falla hasta que `sentinel/frontend/redirect/catalog.ts`
se actualice (la pantalla no puede ofrecer lo que la API rechaza, ni esconder lo que acepta).
"""
import pytest
import re
from pathlib import Path

import yaml

from sentinel.engine import redirect_credentials as rc
from sentinel.redirect import models as m

ROOT = Path(__file__).resolve().parents[3]
FE = ROOT / "sentinel/frontend"
CATALOG = (FE / "redirect/catalog.ts").read_text()


def _tuple(name: str) -> tuple:
    body = re.search(rf"export const {name}(?::[^=]*)? = \[(.*?)\]", CATALOG, re.S).group(1)
    return tuple(re.findall(r'"([^"]+)"', body))


def _record_keys(name: str) -> set:
    body = re.search(rf"export const {name}[^=]*= \{{(.*?)\n\}};", CATALOG, re.S).group(1)
    return set(re.findall(r"^\s*([a-z_]+):", body, re.M))


def test_enums_iguales_al_backend():
    assert _tuple("PROVIDERS") == m.PROVIDERS
    assert _tuple("PROTOCOL_FAMILIES") == m.PROTOCOL_FAMILIES
    assert _tuple("FACES") == m.FACES
    assert _tuple("FAMILY_TIERS") == m.FAMILY_TIERS
    assert _tuple("LABEL_MODES") == m.LABEL_MODES
    assert _tuple("REQUEST_CLASSES") == m.REQUEST_CLASSES
    assert set(_tuple("SCOPE_TYPES")) == set(m.SCOPE_TYPES)
    assert _tuple("POLICY_STATES") == m.POLICY_STATES
    assert _tuple("POSTURE_MODES") == m.POSTURE_MODES


def test_forma_de_credencial_y_base_iguales_al_backend():
    body = re.search(r"export const CREDENTIAL_SHAPES[^=]*= \{(.*?)\n\};", CATALOG, re.S).group(1)
    shapes = {}
    for prov, req, opt in re.findall(r"(\w+): \[\[(.*?)\], \[(.*?)\]\]", body):
        shapes[prov] = (set(re.findall(r'"([^"]+)"', req)), set(re.findall(r'"([^"]+)"', opt)))
    assert shapes == {p: (set(r), set(o)) for p, (r, o) in rc.SHAPES.items()}
    assert set(_tuple("REQUIRES_API_BASE")) == set(rc.REQUIRES_API_BASE)
    assert rc.DEFAULT_API_BASE["openrouter"] in CATALOG
    assert 'ENV_NAME_PREFIX = "REDIRECT_CRED_"' in CATALOG and rc.ENV_PREFIX == "env:"
    # todo proveedor del backend tiene etiqueta y familia sugerida en la pantalla
    assert _record_keys("PROVIDER_LABELS") == set(m.PROVIDERS)
    assert _record_keys("SUGGESTED_PROTOCOL") == set(m.PROVIDERS)


def test_en_pages_solo_hay_modulos_de_entrada():
    # el registry importa TODO `*.ts(x)` del directorio: helpers o tests ahí serían «páginas»
    assert sorted(p.name for p in (FE / "pages").iterdir()) == ["modelos.tsx"]


@pytest.mark.skip(reason='Lee .github/workflows/release.yml de Sentinel; en Eleia la imagen -ext del panel la fija deploy/release/checks/test_ext_images.sh (T091). 057 T017')
def test_la_imagen_del_frontend_se_construye_con_las_paginas():
    dockerfile = (ROOT / "sentinel/docker/frontend.Dockerfile").read_text()
    assert "ENV VITE_PLUGIN_PAGES_DIR=../sentinel/frontend/pages" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile and "USER sentinel" in dockerfile
    assert "__tests__" in dockerfile                       # los tests no entran a la imagen
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    runs = "\n".join(s.get("run", "") for s in release["jobs"]["build-publish"]["steps"])
    assert "-f sentinel/docker/frontend.Dockerfile" in runs
    assert runs.index("publish.sh") < runs.index("sentinel/docker/frontend.Dockerfile")
    # la base no se toca: su Dockerfile sigue sin saber de las páginas
    assert "PLUGIN_PAGES" not in (ROOT / "deploy/docker/frontend.prod.Dockerfile").read_text()


def test_ui_sin_nombre_de_marca_ni_de_motor():
    prohibidos = [l.strip() for l in (ROOT / "deploy/release/checks/prohibited_names.txt").read_text().splitlines()
                  if l.strip() and not l.startswith("#")] + ["sentinel"]
    for f in list((FE / "redirect").glob("*.ts*")) + list((FE / "pages").glob("*.ts*")):
        # solo el texto que se muestra: literales entre comillas y texto JSX (no rutas de import)
        src = re.sub(r'^import .*$', "", f.read_text(), flags=re.M)
        visibles = re.findall(r'"([^"]*)"|>([^<>{}]+)<', src)
        texto = " ".join(a or b for a, b in visibles).lower()
        for nombre in prohibidos:
            assert nombre not in texto, f"{f.name}: «{nombre}» visible"
