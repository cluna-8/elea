"""Contract test de los CANDADOS DEL MOTOR sobre el runtime local: tope de paralelismo y
reintentos (#151; decisiones ② y ③ del #134, selladas por JF el 12-ago — ver ADR-0003).

Lo que se fija acá es el lado del MOTOR del nodo C1. El primer candado —el tope de admisión
del backend (`engine_gate.py`)— ya tiene sus tests; éstos protegen el caso en que aquél no
alcanza:

* el runtime local **serializa** las generaciones y encola **FIFO sin tope**: ése fue el
  principio del cuelgue de la sede del 30-jul, con el producto entero mudo ~10 min porque un
  chat lento se llevó puesto el pool de Postgres;
* el tope del backend es *por proceso del backend*, así que no cubre lo que llegue por otra
  puerta (byok de `/gw`, un worker de más, un tope mal girado en un perfil). Si el motor no
  tiene su propio techo, la cola infinita sigue siendo posible.

Y fija la RELACIÓN entre los dos topes, que es la parte que se rompe sola en cuanto alguien
gira una perilla: el techo del motor tiene que quedar **por encima** del total del backend.
Al revés —motor más bajo que backend— el que empieza a rechazar es el motor, con un error
opaco que no lleva `X-Basa-Rejected`, no deja fila `rejected_saturated` y no lo ve ni el
harness ni el officer que audita. El rechazo tiene que seguir siendo NUESTRO.

El tercer candado es `num_retries: 0` en el mismo deployment: el `num_retries: 2` global del
router es sano contra un proveedor cloud, pero contra un upstream que serializa multiplica por
tres el trabajo que ya no entra — cada generación expirada vuelve a la MISMA cola dos veces
más. Es amplificación, no resiliencia.

Que la imagen pinneada del motor HONRE los dos valores (1.92.0 construye un
`asyncio.Semaphore` por deployment, y el `num_retries` del deployment pisa al global: 3
intentos → 1) se verifica contra la imagen real en
`deploy/release/checks/test_engine_local_limits.sh`: acá no hay motor, y afirmarlo desde pytest
sería creerle a un comentario.
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

from src.services import engine_gate

# Tope sellado en el #151 (propuesta técnica del #134): «~20 = tope backend total + margen».
TOPE_PARALELISMO_LOCAL = 20

# Reintentos del router contra el runtime local (decisión #134-②, JF 12-ago). CERO, y no «los
# del global»: reintentar contra una cola FIFO que serializa es ×3 trabajo por pedido en el
# peor momento posible. No apaga los fallbacks —son otra capa— ni toca a los proveedores
# cloud, que conservan los 2 reintentos globales.
REINTENTOS_LOCAL = 0

# Workers del perfil de producción: `WEB_CONCURRENCY: "${WEB_CONCURRENCY:-2}"` en
# deploy/docker/compose.prod.yml. Se repite acá como constante en vez de leerse del compose
# porque esta suite corre en un contenedor que sólo monta `backend/` y `litellm/` — la raíz
# del repo no existe para pytest. Que el perfil siga diciendo 2 lo verifica el gate de
# despliegue (`checks/test_engine_admission_wiring.sh`), que sí ve el fichero.
WORKERS_PERFIL_PROD = 2


def _catalogo_del_motor() -> dict:
    """El `config.yaml` del motor, resuelto igual que en producción (`src/api/chat.py`):
    la copia montada dentro del contenedor y, si no está, la del repo."""
    ruta = Path("/app/litellm_config/config.yaml")
    if not ruta.exists():
        ruta = Path(__file__).resolve().parents[3] / "litellm" / "config.yaml"
    assert ruta.exists(), f"no encuentro el catálogo del motor (probé {ruta})"
    return yaml.safe_load(ruta.read_text())


def _deployments_locales(catalogo: dict) -> list[dict]:
    """Entradas del `model_list` que hablan con el runtime local CONVERSABLE.

    El discriminante es el prefijo `ollama_chat/` y no el nombre del alias: el alias cambia
    por cliente (`<slug>-local`, `ollama-qwen3-4b`) y un test atado al alias dejaría de
    mirar el deployment de verdad en cuanto alguien renombre.

    Las **embeddings** del auto-router (prefijo `ollama/`) quedan fuera a propósito: sale una
    por chat y los chats ya vienen acotados por el tope del backend, así que ponerles techo
    no quitaría ninguna cola —sólo agregaría un modo de degradación nuevo al ruteo.
    """
    return [
        d for d in catalogo.get("model_list", [])
        if str(d.get("litellm_params", {}).get("model", "")).startswith("ollama_chat/")
    ]


def _default_del_codigo(constante: str):
    """Valor de `constante` con las envs de admisión AUSENTES, o sea el default que se
    embarca.

    Se ejecuta el módulo de nuevo como copia aparte (misma técnica y mismo porqué que
    `tests/unit/test_engine_gate.py`: un `reload` reemplazaría `EngineSaturatedError` por
    otra clase y envenenaría a todo test posterior que ejercite el rechazo). Hace falta
    porque el contenedor de la suite ahora SÍ trae las envs cableadas: leer la constante viva
    ataría este contrato al valor que tenga puesto quien corre los tests, y lo que se afirma
    es la relación entre los valores que se EMBARCAN.
    """
    with pytest.MonkeyPatch.context() as m:
        for env in ("BASA_ENGINE_MAX_CONCURRENCY", "BASA_ENGINE_QUEUE_TIMEOUT_SECONDS"):
            m.delenv(env, raising=False)
        spec = importlib.util.spec_from_file_location(
            "engine_gate_copia_contrato_paralelismo", Path(engine_gate.__file__))
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    return getattr(modulo, constante)


def test_el_catalogo_tiene_deployments_del_runtime_local():
    """Guarda anti-verde-por-casualidad: si el catálogo se reestructura o el prefijo cambia,
    los tests de abajo iterarían una lista vacía y pasarían sin mirar nada."""
    assert _deployments_locales(_catalogo_del_motor()), (
        "ningún deployment `ollama_chat/` en el catálogo del motor — o cambió la forma del "
        "config, o este contrato dejó de mirar lo que dice mirar")


def test_el_deployment_local_declara_su_tope_de_paralelismo():
    """El techo del motor existe y es el valor sellado, en el sitio donde el motor lo lee
    (`litellm_params`, no `model_info`) y con el tipo que espera (entero, no `"20"`)."""
    for deployment in _deployments_locales(_catalogo_del_motor()):
        alias = deployment.get("model_name")
        params = deployment["litellm_params"]
        assert "max_parallel_requests" in params, (
            f"el deployment local `{alias}` no tiene tope de paralelismo: el runtime local "
            "serializa y encola FIFO sin límite — sin este techo la cola infinita del 30-jul "
            "sigue siendo posible por cualquier puerta que no pase por el gate del backend")
        tope = params["max_parallel_requests"]
        assert isinstance(tope, int) and not isinstance(tope, bool), (
            f"`{alias}`: max_parallel_requests={tope!r} no es un entero — el motor calcula el "
            "semáforo con aritmética; un string lo rompe o lo ignora")
        assert tope == TOPE_PARALELISMO_LOCAL, (
            f"`{alias}`: max_parallel_requests={tope}, esperado {TOPE_PARALELISMO_LOCAL} "
            "(#151/#134). Moverlo es una decisión de capacidad, no un ajuste suelto: cambiar "
            "el valor exige mover también esta constante y decir por qué")


def test_el_deployment_local_no_reintenta():
    """Los reintentos del router contra el runtime local van en 0 (#134-②).

    El `num_retries: 2` de `router_settings` es sano contra un proveedor cloud —un 429 se
    reintenta y listo—, pero contra un upstream que serializa y encola FIFO cada reintento
    vuelve a la MISMA cola: ×3 trabajo por pedido justo cuando el sistema ya no da abasto.
    Fue parte del diagnóstico del cuelgue del 30-jul.

    Se exige la clave EN EL DEPLOYMENT y no confiar en el global: el valor por deployment es
    el único que puede ser distinto del que necesita el cloud, y el global lo escribe/lee
    también el alta de modelos por panel.
    """
    for deployment in _deployments_locales(_catalogo_del_motor()):
        alias = deployment.get("model_name")
        params = deployment["litellm_params"]
        assert "num_retries" in params, (
            f"el deployment local `{alias}` no fija num_retries: hereda los reintentos "
            "globales (pensados para el cloud) y cada generación que expira vuelve a la cola "
            "FIFO dos veces más — amplificación, no resiliencia (#134-②)")
        reintentos = params["num_retries"]
        assert isinstance(reintentos, int) and not isinstance(reintentos, bool), (
            f"`{alias}`: num_retries={reintentos!r} no es un entero")
        assert reintentos == REINTENTOS_LOCAL, (
            f"`{alias}`: num_retries={reintentos}, esperado {REINTENTOS_LOCAL} (#134-②, "
            "sellado por JF el 12-ago; ver ADR-0003)")


def test_el_techo_del_motor_queda_por_encima_del_tope_total_del_backend():
    """La relación entre los dos candados, que es lo que se rompe al girar una perilla sola.

    Total que el backend puede tener en vuelo = tope por proceso × workers del perfil prod.
    El techo del motor tiene que superarlo: así el primero en decir que no es SIEMPRE el
    backend, que rechaza con el 503 honesto, con `X-Basa-Rejected: saturated` y con fila
    durable `rejected_saturated`. Si el motor quedara por debajo, el rechazo lo daría él —un
    error opaco, sin cabecera, sin auditoría y sin nadie que lo cuente— y el producto perdería
    justo la propiedad que el nodo C1 vino a comprar: que saturar se VEA.
    """
    total_backend = _default_del_codigo("ENGINE_MAX_CONCURRENCY") * WORKERS_PERFIL_PROD
    assert TOPE_PARALELISMO_LOCAL > total_backend, (
        f"el techo del motor ({TOPE_PARALELISMO_LOCAL}) no supera al total del backend "
        f"({total_backend} = {_default_del_codigo('ENGINE_MAX_CONCURRENCY')} por proceso × "
        f"{WORKERS_PERFIL_PROD} workers): el motor empezaría a rechazar antes que el gate, y "
        "ese rechazo no es honesto ni auditado")
