"""Contract test del compose: el backend RECIBE `BASA_ENTITY_REGION` (#137/#141).

Hallazgo del gate de #137 (verificado por el manager): `gateway.py` lee
`os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION)` desde antes de este PR
— el código consumidor siempre estuvo bien. Lo que faltaba era la ENTREGA: ni
`docker-compose.yml` ni `deploy/docker/compose.prod.yml` declaraban esta env en el
bloque `backend` (sólo en `litellm`), así que en una instalación real `/gw`,
`/gw/inspect` (extensión de navegador) y el Playground SIEMPRE resolvían al default
del código (`eu`), sin importar qué región eligiera la instalación — el motor (byok)
sí la recibía y los otros tres planos no.

Este test fija la mitad de la ENTREGA que un test de comportamiento (monkeypatch del
proceso) no puede: `monkeypatch.setenv` prueba que el CÓDIGO usa la env si la tiene,
pero pasaría igual de verde con o sin la línea de compose, porque nunca pasa por
docker-compose. Sin este test, una línea de YAML borrada por accidente (rebase, merge,
"limpieza") no la nota nadie hasta que un cliente latam se instala y sale con
recognizers de España — el mismo bug que este PR arregla, de vuelta y en silencio.

La otra mitad —¿el backend, ya con la env adentro, la usa de verdad?— la fija
`test_gateway_nlp_paridad.py::test_region_de_instalacion_llega_al_analyzer_de_gw`.
Las dos juntas cierran el círculo: la línea existe (acá) Y hace algo (allá).

POR QUÉ VIVE EN `harness/` Y NO EN `backend/tests/`: la suite de backend corre en
CI dentro del contenedor (`docker compose run --rm --no-deps backend pytest tests/`),
cuyo build context es `./backend` — la raíz del repo NO existe ahí, así que los dos
compose son inalcanzables y el assert de existencia no puede pasar nunca. La
restricción ya estaba documentada en `backend/tests/contract/
test_catalogo_motor_paralelismo.py`, que por eso repite el dato del compose como
constante en vez de leerlo. El job `harness-tests` sí corre sobre el checkout del
host (`actions/checkout@v4` + `pytest tests/` en `harness/`) y trae `pyyaml`, así
que acá el test lee los ficheros de verdad — que es el único modo de que pinee algo."""
from pathlib import Path

import yaml

# harness/tests/<este archivo> → parents[2] es la raíz del repo.
_REPO = Path(__file__).resolve().parents[2]
_DEV_COMPOSE = _REPO / "docker-compose.yml"
_PROD_COMPOSE = _REPO / "deploy" / "docker" / "compose.prod.yml"


def _cargar(ruta: Path) -> dict:
    assert ruta.exists(), f"no encuentro el compose ({ruta})"
    return yaml.safe_load(ruta.read_text())


def _env_declara_region(servicio_environment) -> bool:
    """`environment` de un servicio compose puede ser lista (`KEY=value`, dev) o
    dict (`KEY: value`, prod) — los dos estilos conviven en este repo."""
    if isinstance(servicio_environment, dict):
        return "BASA_ENTITY_REGION" in servicio_environment
    if isinstance(servicio_environment, list):
        return any(
            isinstance(item, str) and item.split("=", 1)[0] == "BASA_ENTITY_REGION"
            for item in servicio_environment
        )
    return False


def test_backend_recibe_basa_entity_region_en_compose_dev():
    compose = _cargar(_DEV_COMPOSE)
    backend_env = compose["services"]["backend"]["environment"]
    assert _env_declara_region(backend_env), (
        "docker-compose.yml: el bloque `backend` no declara BASA_ENTITY_REGION — "
        "`/gw`, la extensión de navegador y el Playground van a resolver siempre "
        "el default del código (eu), sin importar la región de la instalación "
        "(#137/#141, hallazgo H1)."
    )


def test_backend_recibe_basa_entity_region_en_compose_prod():
    compose = _cargar(_PROD_COMPOSE)
    backend_env = compose["services"]["backend"]["environment"]
    assert _env_declara_region(backend_env), (
        "deploy/docker/compose.prod.yml: el bloque `backend` no declara "
        "BASA_ENTITY_REGION — mismo hallazgo que en el compose de dev (#137/#141)."
    )


def test_litellm_y_backend_apuntan_al_mismo_default_de_instalacion():
    """Los dos servicios tienen que resolver la MISMA región de instalación — si uno
    trae un default distinto al otro, el mismo texto detecta entidades distintas según
    el plano por el que entró (byok vs /gw), justo lo que el ADR-0003 prohíbe."""
    for ruta in (_DEV_COMPOSE, _PROD_COMPOSE):
        compose = _cargar(ruta)
        litellm_env = compose["services"]["litellm"]["environment"]
        backend_env = compose["services"]["backend"]["environment"]
        assert _env_declara_region(litellm_env), f"{ruta.name}: litellm sin BASA_ENTITY_REGION"
        assert _env_declara_region(backend_env), f"{ruta.name}: backend sin BASA_ENTITY_REGION"
