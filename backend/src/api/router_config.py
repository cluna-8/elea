"""API admin de la config del auto-router semántico (spec 030, US2 · T011).

Contrato: `specs/030-semantic-auto-router/contracts/router-config-api.md`.
Schema y reglas de validación: `data-model.md` §1.

Dos endpoints sobre el MISMO fichero caliente que lee el runtime del router
(`auto_router.json` del volumen `litellm_config`):

- `GET  /api/v1/chat/router-config` → la config + los campos COMPUTADOS que el panel
  necesita para señalar roturas (`default_model_ok`, `embedding_model_ok`, `target_ok`
  por ruta, `config_error`).
- `PUT  /api/v1/chat/router-config` → valida, escribe atómicamente y devuelve lo releído.

Tres decisiones que este módulo sostiene:

1. **Los computados no se persisten.** Son una foto del catálogo del motor EN ESTE
   INSTANTE (el admin puede borrar un modelo un segundo después de guardar). Guardarlos
   sería escribir en disco un estado derivado que envejece mal, y por eso el PUT los
   descarta del cuerpo entrante en vez de confiar en que el cliente los omita.
2. **El GET nunca devuelve 500.** Config ausente o corrupta ⇒ 200 con defaults seguros
   (`enabled: false`, rutas vacías) + `config_error: true`. Un panel que revienta con un
   JSON roto deja al admin sin la única pantalla desde la que podría arreglarlo; y el
   runtime ya degrada al default por su cuenta (FR-004), así que el 500 no protegería nada.
3. **La existencia del `target_model` en el catálogo NO se valida al guardar** (data-model
   §1): el catálogo cambia después igual. La ruta rota se SEÑALA (`target_ok: false`) y el
   runtime cae al default.
"""
import copy
import logging
import os
from typing import Any

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..auth.rbac import require_role
from ..services import auto_router_service
# El catálogo se lee con EXACTAMENTE el mismo helper de path que `GET /chat/models`
# (chat.py): el panel tiene que comparar contra lo que el dropdown ofrece de verdad, no
# contra una segunda resolución de path que puede divergir del plano chat.
from .chat import _get_config_path as _engine_config_path

router = APIRouter(prefix="/chat", tags=["Auto Router"])
logger = logging.getLogger("basa-secure-gateway.router-config")

# Mismo guard que el resto de endpoints de gestión del plano chat (register_model,
# delete_model, PUT /fallbacks): sesión JWT válida y rol efectivo admin o developer.
# Fail-closed: sin credencial 401, con rol insuficiente 403. Las virtual keys (sk-*) no
# resuelven a usuario de sesión, así que tampoco llegan acá — por diseño.
_SOLO_ADMIN = Depends(require_role("admin", "developer"))

# Campos COMPUTADOS: sólo salen en el GET, jamás entran al fichero.
_COMPUTADOS_RAIZ = ("default_model_ok", "embedding_model_ok", "config_error")
_COMPUTADO_RUTA = "target_ok"


def _catalogo_del_motor() -> set:
    """`model_name`s del catálogo real del motor (`model_list` del config.yaml).

    Si el config no se puede leer se devuelve conjunto vacío: los computados quedan en
    `false` (señal honesta de "no verificable") y el endpoint sigue respondiendo 200.
    """
    try:
        with open(_engine_config_path(), "r") as fichero:
            datos = yaml.safe_load(fichero) or {}
    except Exception as exc:  # noqa: BLE001 — el catálogo es best-effort para el panel
        logger.warning("No se pudo leer el catálogo del motor para los computados: %s", exc)
        return set()
    return {
        entrada.get("model_name")
        for entrada in (datos.get("model_list") or [])
        if isinstance(entrada, dict) and entrada.get("model_name")
    }


def _defaults_seguros() -> dict:
    """Copia PROFUNDA del default del servicio (`enabled: false`, rutas vacías).

    Profunda a propósito: `DEFAULT_CONFIG` es un dict de módulo con una lista mutable
    dentro; una copia superficial la compartiría y un accidente en la respuesta se
    convertiría en un cambio permanente del default del proceso.
    """
    return copy.deepcopy(auto_router_service.DEFAULT_CONFIG)


def _leer_para_panel() -> tuple:
    """(config, config_error). Nunca lanza: el panel siempre recibe algo servible.

    `config_error: true` cubre los dos casos en que lo que hay en disco NO es una config
    válida y el admin está viendo defaults (contrato §GET): fichero ausente y fichero
    ilegible/corrupto. Ausente cuenta porque el fichero viaja en el seed del perfil y lo
    copia el release al volumen: que falte es un despliegue incompleto, no un estado
    normal — y el panel debe decirlo en vez de fingir una config vacía legítima.
    """
    try:
        ruta = auto_router_service.get_config_path()
        if not os.path.exists(ruta):
            logger.info("auto_router.json ausente en %s: el panel recibe defaults seguros", ruta)
            return _defaults_seguros(), True
        return auto_router_service.load_config(), False
    except Exception as exc:  # noqa: BLE001 — contrato: el GET nunca es 500
        logger.warning("auto_router.json ilegible (%s): el panel recibe defaults seguros", exc)
        return _defaults_seguros(), True


def _con_computados(config: dict, *, config_error: bool) -> dict:
    """La config tal cual está en disco + los campos derivados del catálogo.

    Las rutas se copian preservando SÓLO las claves que traen: no se rellenan `description`
    ni `tier` con `null`. Una clave presente con valor nulo rompe a los consumidores que
    hacen `.get(campo, default)` — el default no aplica cuando la clave existe.
    """
    catalogo = _catalogo_del_motor()
    rutas = []
    for ruta in config.get("routes") or []:
        if not isinstance(ruta, dict):
            continue
        salida = dict(ruta)
        salida[_COMPUTADO_RUTA] = salida.get("target_model") in catalogo
        rutas.append(salida)

    respuesta = dict(config)
    respuesta["routes"] = rutas
    respuesta["default_model_ok"] = config.get("default_model") in catalogo
    respuesta["embedding_model_ok"] = config.get("embedding_model") in catalogo
    respuesta["config_error"] = config_error
    return respuesta


def _sin_computados(payload: dict) -> dict:
    """Quita los campos computados del cuerpo entrante (ver decisión 1 del módulo).

    El panel hace GET → editar → PUT con el MISMO objeto, así que los computados vuelven
    aunque el contrato diga que el body va sin ellos. Se descartan en silencio; el resto
    del objeto se respeta tal cual llegó (nada de whitelist: un campo nuevo del schema no
    tiene que morir en este filtro).
    """
    limpio = {clave: valor for clave, valor in payload.items() if clave not in _COMPUTADOS_RAIZ}
    rutas = limpio.get("routes")
    if isinstance(rutas, list):
        limpio["routes"] = [
            {clave: valor for clave, valor in ruta.items() if clave != _COMPUTADO_RUTA}
            if isinstance(ruta, dict) else ruta
            for ruta in rutas
        ]
    return limpio


@router.get("/router-config", dependencies=[_SOLO_ADMIN])
def get_router_config():
    """Config del router + computados. 200 siempre (contrato §GET)."""
    config, config_error = _leer_para_panel()
    return _con_computados(config, config_error=config_error)


@router.put("/router-config", dependencies=[_SOLO_ADMIN])
def put_router_config(payload: dict[str, Any] = Body(...)):
    """Valida (422 con detalle), escribe atómicamente y devuelve el config RELEÍDO.

    Releído y no el entrante: lo que el panel muestra después de guardar tiene que ser lo
    que quedó en disco, que es lo que el runtime va a leer en la siguiente consulta.
    """
    entrante = _sin_computados(payload)

    errores = auto_router_service.validate_config(entrante)
    if errores:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errores)

    try:
        auto_router_service.save_config(entrante)
    except Exception as exc:  # noqa: BLE001 — escritura fallida se reporta, no se traga
        logger.error("No se pudo guardar auto_router.json: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo guardar la configuración del router.",
        )

    config, config_error = _leer_para_panel()
    return _con_computados(config, config_error=config_error)
