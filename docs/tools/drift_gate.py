"""Gate de drift doc ↔ código (DevRel · «La Imprenta»).

Compara lo que el producto PROMETE por escrito contra lo que el código HACE, en tres
ejes, y emite un veredicto legible por máquina. Determinista, sin dependencias fuera
de la stdlib y sin levantar el stack: corre en cualquier checkout limpio y en CI.

Por qué existe: el check de deriva que ya teníamos regenera
`docs/docs/api-reference/configuration.md` desde `.env.example` y diffea. Es un lazo
CERRADO — verifica que la página coincida con el `.env.example`, jamás que el
`.env.example` coincida con lo que el código lee de verdad. Una variable que el
backend usa y nadie declaró es invisible para ese check y para la doc.

Ejes:
  A · rutas     código (`@router.<verb>`) ↔ `docs/docs/api-reference/openapi.json`
  B · config    env leídas por LOS DOS PLANOS (backend + motor) ↔ `.env.example`
  C · contratos literales de estado que ve un integrador ↔ `docs/docs/**`

Categorías del veredicto:
  documentado_no_existe  — la doc promete algo que el código no tiene. Es una MENTIRA.
  existe_no_documentado  — el código lo hace y nadie lo escribió.

Tres decisiones de calibración, todas contra falsos positivos medidos en la primera
corrida — un gate que grita lobo se ignora, así que este PREFIERE callarse:

1. `include_in_schema=False` manda. El router `/internal` se excluye del openapi a
   propósito (`backend/src/api/internal.py:39`); FastAPI lo respeta y este gate
   también. Ausencia deliberada no es deriva.
2. Los dos planos cuentan **para el eje B, vía `litellm/config.yaml`**. El motor lee
   sus llaves por `os.environ/VAR` en ese YAML; mirando sólo `backend/src`, once
   variables reales aparecían como mentiras.
3. Contrato ≠ identificador. `blocked_*` y `rejected_*` son razones que viajan al
   cliente; `audit_logs` o `license_id` son nombres de campo internos. El eje C sólo
   mira lo primero, más los estados de licencia declarados abajo. Acotar de menos
   deja hallazgos sin ver; acotar de más entrena al equipo a ignorar el gate.

Uso:
    python3 docs/tools/drift_gate.py              # tabla en consola
    python3 docs/tools/drift_gate.py --json out.json

Salida: 0 si no hay `documentado_no_existe`; 1 si hay al menos uno; **1 si falta
`openapi.json` o `.env.example`** (fail-closed — un gate que reporta PASS porque no
tuvo con qué comparar es peor que uno que no corre).

## Lo que este gate NO mira — declarado, no descubierto por accidente

Verificado adversarialmente el 13-ago (18 agentes, revisión + verificación cruzada de
cada hallazgo). El instrumento es honesto en los tres ejes que sí ejecuta; estos son
sus bordes reales, no una lista aspiracional:

- **El eje C es de una sola dirección.** `contratos_documentados()` deriva "lo
  documentado" INTERSECTANDO los literales ya extraídos del código con el texto de
  `docs/docs/**` — nunca extrae literales DESDE la doc para compararlos contra el
  código. Por construcción, el eje C solo puede emitir `existe_no_documentado`, jamás
  `documentado_no_existe`: una doc que prometiera un literal inventado (uno que el
  código nunca emite) pasaría en silencio. **"0 mentiras" es verdad en los ejes A
  (rutas) y B (config) — los únicos que comparan en las dos direcciones — no en C.**
- **El plano `litellm/extensions/*.py` (motor, Python) está fuera de los ejes B y C.**
  `env_del_codigo()` y `contratos_del_codigo()` recorren `backend/src/**`; la única
  cobertura del motor es la lectura de `litellm/config.yaml` (eje B, sintaxis
  `os.environ/VAR`) — el código *Python* del motor (`basa_guardrail.py`,
  `basa_guardian_policy.py`, `basa_audit_logger.py`…) no se escanea en ningún eje.
  Contratos que solo emite ese plano (p. ej. `blocked_entity_type`,
  `blocked_nlp_unavailable`) y variables que solo lee por `os.environ.get` desde ahí
  (p. ej. `BASA_AUDIT_FAIL`, capturada hoy solo de rebote vía el compose y mal
  etiquetada `orquestacion`) son invisibles al gate.
- **El eje A compara PATHS, nunca verbos.** `rutas_del_codigo()`/`rutas_del_contrato()`
  calculan `{ruta: {verbos}}`, pero `construir_veredicto()` solo resta *claves* de los
  dos dicts — nunca compara los sets de verbos de una ruta que existe en ambos lados.
  Un método fantasma en el openapi (o uno real que falta ahí) para una ruta cuyo path
  ya coincide pasa en silencio. Caso real detectado hoy: `/compliance/consent/{}`
  tiene `DELETE` en el código y no en el openapi publicado — invisible en el "74=74".
- **Colisión de normalización real**: `/compliance/consent/{user_id}` (list) y
  `/compliance/consent/{consent_id}` (delete) son dos endpoints distintos que
  `normalizar()` funde en una sola clave `/compliance/consent/{}` — es la causa directa
  del punto anterior.
- **Rutas fuera de `backend/src/api/*.py` son invisibles.** `@app.get("/health")` vive
  en `backend/src/main.py`, fuera de `API_DIR`; el gate no lo ve en ningún eje.
- **La prosa de `docs/docs/**` nunca se cruza contra el código.** El eje C solo detecta
  TOKENS que matchean `CONTRACT_RE` o están en `ESTADOS_LICENCIA` — no tiene forma de
  detectar una afirmación en prosa como "cada request atraviesa cinco capas" o "son 4
  servicios en producción". Las 5 correcciones de este mismo PR se encontraron
  leyendo a mano, no con este gate — ninguna involucraba un literal de contrato.
  Demostrado: restaurar las 2 páginas corregidas a su versión previa a este PR y
  correr el gate da 0 hallazgos nuevos — detección 0/5 sobre la clase de drift que
  motivó su construcción.

Estos siete puntos son backlog con nombre (ver issues enlazados desde el PR que cerró
esta ronda), no deuda oculta. Un instrumento que declara sus bordes es más confiable
que uno que promete cubrir más de lo que ejecuta.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

API_DIR = REPO / "backend" / "src" / "api"
BACKEND_SRC = REPO / "backend" / "src"
MOTOR_CONFIG = REPO / "litellm" / "config.yaml"
COMPOSES = (REPO / "docker-compose.yml", REPO / "deploy" / "docker" / "compose.prod.yml")
OPENAPI = REPO / "docs" / "docs" / "api-reference" / "openapi.json"
ENV_EXAMPLE = REPO / ".env.example"
DOCS_PRODUCTO = REPO / "docs" / "docs"

VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Prefijo de montaje común: `api_router` (backend/src/api/__init__.py) y los dos
# routers que main.py incluye a mano cuelgan todos de /api/v1. Se normaliza a ambos
# lados para no comparar manzanas con peras.
MOUNT = "/api/v1"

# Literales de estado que un integrador ve en una respuesta o cabecera. No son
# strings internos: son contrato. Si el código los emite y la doc no los explica,
# el que integra no sabe qué hacer cuando le llegan.
CONTRACT_RE = re.compile(r"^(rejected|blocked)_[a-z0-9_]+$")

# Coinciden con CONTRACT_RE por forma pero NO son un `compliance_status` que un
# integrador vea — son otra cosa que se llama parecido:
#   blocked_by_layer  — nombre de COLUMNA/campo (`audit.py:45`); guarda CUÁL capa
#                        bloqueó, su valor es un id de capa, nunca el string
#                        "blocked_by_layer" en sí.
#   blocked_topics    — clave de config de un Guardian SEED con `is_active=False`
#                        (`guardian_service.py:158`) — lista de temas, no un
#                        estado, y ni siquiera corre hoy.
# Calibración del 13-ago: aparecieron en la primera pasada de la tabla de
# contratos del ítem 3 del backlog y se verificaron falsos antes de publicar.
CONTRACT_NO_ES_ESTADO = frozenset({"blocked_by_layer", "blocked_topics"})

# Estados de licencia que llegan al cliente (403/402 y el health de licencia). Van
# explícitos y no por prefijo `license_*`: ese prefijo también nombra campos internos
# (`license_id`, `license_status`), y mezclarlos convierte el eje en ruido.
ESTADOS_LICENCIA = frozenset({
    "license_expired", "license_grace", "license_invalid", "license_missing",
    "license_over_seat", "license_tenant_mismatch", "license_seat_limit_exceeded",
    "license_creation_blocked", "license_clock_rollback_suspected", "license_degraded",
})

# El motor no es Python: interpola sus llaves con `os.environ/VAR` en su YAML.
MOTOR_ENV_RE = re.compile(r"os\.environ/([A-Z][A-Z0-9_]*)")

# `${VAR}` y `${VAR:-default}` en los composes: el punto donde una variable del
# operador se consume, aunque adentro del contenedor se llame distinto.
COMPOSE_ENV_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)[:\-}]")

NOMBRE_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

# Variables que el proceso NO declara porque las pone el entorno de ejecución
# (docker, CI, el shell). Declararlas en .env.example sería ruido, no honestidad.
ENV_IGNORADAS = {
    "PATH", "HOME", "PWD", "USER", "LANG", "TZ", "HOSTNAME", "PYTHONPATH",
    "PYTEST_CURRENT_TEST", "CI", "TERM", "VIRTUAL_ENV",
}


def _str_const(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _punteado(node: ast.AST) -> str:
    """`os.environ.get` para un Attribute anidado; `_env_int` para un Name."""
    partes: list[str] = []
    while isinstance(node, ast.Attribute):
        partes.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        partes.append(node.id)
    return ".".join(reversed(partes))


# ── eje A · rutas ────────────────────────────────────────────────────────────────
# Los dos lugares donde se monta un router. De acá sale la lista de fuentes a escanear:
# lo que no está montado no sirve tráfico y no debería contar como ruta del código.
PUNTOS_DE_MONTAJE = ("backend/src/api/__init__.py", "backend/src/main.py")


def _resolver_import_relativo(origen: Path, modulo: str | None, level: int) -> Path | None:
    """`from ..sso.api import router` en `backend/src/api/__init__.py` → `backend/src/sso/api.py`.

    `origen.parent` ya es el directorio del paquete actual en los dos casos que nos
    importan: para un `__init__.py` es su propio paquete, y para un módulo suelto como
    `main.py` es el paquete que lo contiene. Cada nivel extra sube uno.
    """
    paquete = origen.parent
    for _ in range(level - 1):
        paquete = paquete.parent
    destino = paquete.joinpath(*modulo.split(".")) if modulo else paquete
    for candidato in (destino.with_suffix(".py"), destino / "__init__.py"):
        if candidato.is_file():
            return candidato.resolve()
    return None


def modulos_con_rutas() -> list[Path]:
    """Fuentes que declaran endpoints: las de `api/` MÁS los routers montados desde
    fuera de ese paquete.

    `API_DIR.glob("*.py")` no es recursivo, así que un router en un paquete nuevo era
    invisible para este eje mientras el OpenAPI —que sale de la app VIVA— sí lo veía.
    Resultado: el gate reportaba las rutas reales de `sso/api.py` como MENTIRA del
    openapi (#266). El modelo per-archivo de prefijos ya servía; el agujero era el glob.

    Se deriva de los `from … import router` de los puntos de montaje en vez de ensanchar
    el glob a `**/*.py`, por dos razones: un router declarado y NUNCA montado no sirve
    tráfico (contarlo inventaría deriva al revés), y así el próximo paquete nuevo entra
    solo, sin que nadie se acuerde de tocar el gate.
    """
    modulos = {p.resolve() for p in API_DIR.glob("*.py")}
    for relativo in PUNTOS_DE_MONTAJE:
        entrada = REPO / relativo
        if not entrada.is_file():
            continue
        try:
            arbol = ast.parse(entrada.read_text(encoding="utf-8"), filename=str(entrada))
        except SyntaxError as exc:
            print(f"⚠  no parsea {relativo}: {exc}", file=sys.stderr)
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.ImportFrom) or not nodo.level:
                continue
            if not any(alias.name == "router" for alias in nodo.names):
                continue
            destino = _resolver_import_relativo(entrada, nodo.module, nodo.level)
            if destino is not None:
                modulos.add(destino)
    return sorted(modulos)


def rutas_del_codigo() -> dict[str, set[str]]:
    """{ruta normalizada: {verbos}} leídas de los decoradores del backend."""
    rutas: dict[str, set[str]] = {}
    for py in modulos_con_rutas():
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:  # un fuente roto es un hallazgo, no un crash
            print(f"⚠  no parsea {py.relative_to(REPO)}: {exc}", file=sys.stderr)
            continue

        # var -> prefix, de `X = APIRouter(prefix="/gw")`. `ocultos` recoge los routers
        # marcados `include_in_schema=False`: su ausencia del openapi es una decisión
        # del backend, no una deriva, y contarla como hallazgo enseña a ignorar el gate.
        prefijos: dict[str, str] = {}
        ocultos: set[str] = set()
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, ast.Call):
                continue
            fn = nodo.value.func
            if getattr(fn, "id", None) != "APIRouter" and getattr(fn, "attr", None) != "APIRouter":
                continue
            prefijo, oculto = "", False
            for kw in nodo.value.keywords:
                if kw.arg == "prefix":
                    prefijo = _str_const(kw.value) or ""
                elif kw.arg == "include_in_schema" and isinstance(kw.value, ast.Constant):
                    oculto = kw.value.value is False
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    prefijos[destino.id] = prefijo
                    if oculto:
                        ocultos.add(destino.id)

        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in nodo.decorator_list:
                if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
                    continue
                verbo = deco.func.attr
                if verbo not in VERBS or not isinstance(deco.func.value, ast.Name):
                    continue
                var = deco.func.value.id
                if var in ocultos:
                    continue
                if any(kw.arg == "include_in_schema" and isinstance(kw.value, ast.Constant)
                       and kw.value.value is False for kw in deco.keywords):
                    continue
                cola = _str_const(deco.args[0]) if deco.args else None
                if cola is None:
                    continue
                rutas.setdefault(normalizar(prefijos.get(var, "") + cola), set()).add(verbo.upper())
    return rutas


def normalizar(ruta: str) -> str:
    """Quita el prefijo de montaje y la barra final; unifica los nombres de los
    parámetros de path (`{user_id}` y `{id}` son la misma ruta para este gate)."""
    if ruta.startswith(MOUNT):
        ruta = ruta[len(MOUNT):]
    ruta = re.sub(r"\{[^}]+\}", "{}", ruta)
    return ruta.rstrip("/") or "/"


class InsumoAusenteError(RuntimeError):
    """El archivo que un eje necesita para comparar no existe.

    Fail-CLOSED a propósito: devolver `{}`/`set()` en silencio hacía que faltar
    `openapi.json` o `.env.example` reportara PASS con 0 mentiras — el gate parecía
    sano porque no tuvo con qué comparar, exactamente lo contrario de lo que un gate
    de honestidad debe hacer cuando pierde su fuente de verdad."""


def rutas_del_contrato() -> dict[str, set[str]]:
    if not OPENAPI.exists():
        raise InsumoAusenteError(f"falta {OPENAPI.relative_to(REPO)} — el eje de rutas no puede comparar")
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    return {
        normalizar(ruta): {v.upper() for v in ops if v.lower() in VERBS}
        for ruta, ops in spec.get("paths", {}).items()
    }


# ── eje B · config ───────────────────────────────────────────────────────────────
def env_del_codigo() -> dict[str, str]:
    """Variables que el producto consume de verdad → `{VAR: origen}`.

    No basta con `os.getenv`: media docena de valores se leen por helpers tipados
    (`_env_int("BASA_ENGINE_MAX_CONCURRENCY", 8, …)` en `services/engine_gate.py`),
    y el motor ni siquiera es Python. Mirando sólo el patrón directo del backend,
    variables vivas se reportaban como muertas.

    El ORIGEN importa para el veredicto: `app` es superficie de configuración del
    producto y su ausencia del `.env.example` es un hueco de documentación real;
    `orquestacion` son perillas del compose (imágenes, puertos, hosts) que ya traen
    default y no le pertenecen a la referencia de configuración. Contarlas juntas
    infla el número y esconde las que sí importan."""
    origen: dict[str, str] = {}

    def anotar(nombre: str, quien: str) -> None:
        # `app` gana: una variable que el compose pasa Y el código lee es config.
        if origen.get(nombre) != "app":
            origen[nombre] = quien

    leidas: set[str] = set()

    for py in BACKEND_SRC.rglob("*.py"):
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8", errors="replace"), filename=str(py))
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            # os.environ["X"]
            if isinstance(nodo, ast.Subscript):
                base = nodo.value
                if isinstance(base, ast.Attribute) and base.attr == "environ":
                    if (nombre := _str_const(nodo.slice)) and NOMBRE_ENV_RE.match(nombre):
                        leidas.add(nombre)
                continue
            # os.getenv("X") · os.environ.get("X") · cualquier helper *env*("X", …)
            if isinstance(nodo, ast.Call) and nodo.args:
                # El nombre PUNTEADO, no el último atributo: en `os.environ.get("X")`
                # el atributo es `get` y mirar sólo eso descartaba lecturas reales.
                if "env" not in _punteado(nodo.func).lower():
                    continue
                if (nombre := _str_const(nodo.args[0])) and NOMBRE_ENV_RE.match(nombre):
                    leidas.add(nombre)

    if MOTOR_CONFIG.exists():
        leidas |= set(MOTOR_ENV_RE.findall(MOTOR_CONFIG.read_text(encoding="utf-8")))

    for nombre in leidas - ENV_IGNORADAS:
        anotar(nombre, "app")

    # El compose también CONSUME: `AZURE_API_KEY=${AZURE_OPENAI_API_KEY}` renombra en
    # la frontera, así que el nombre que el operador pone en su `.env` no es el que
    # el proceso lee. Sin esto, toda variable renombrada al entrar al contenedor se
    # reportaba como declarada-y-muerta.
    for compose in COMPOSES:
        if not compose.exists():
            continue
        # Sin comentarios: `compose.prod.yml:6` explica la convención `${VAR:?}` en
        # prosa, y "VAR" ahí es la metavariable de ejemplo, no una variable real.
        sin_comentarios = "\n".join(
            l.split("#", 1)[0] for l in compose.read_text(encoding="utf-8").splitlines()
        )
        for nombre in COMPOSE_ENV_RE.findall(sin_comentarios):
            if nombre not in ENV_IGNORADAS:
                anotar(nombre, "orquestacion")

    return origen


def env_declaradas() -> set[str]:
    """Variables REALMENTE declaradas en .env.example — la misma definición que usa
    el generador de la referencia (`gen_config_reference.py`), a propósito (#271).

    Antes esta función aceptaba `# VAR=`, y el generador no. En el hueco entre las
    dos definiciones cabían variables que el gate daba por documentadas y que la
    referencia que se le muestra al cliente no mencionaba jamás — entre ellas
    `BASA_ALLOW_DEV_LICENSE`, la que habilita claves de licencia de desarrollo. El
    gate se callaba sobre exactamente la clase de cosa que dice vigilar.

    La pregunta que responde el eje de config es «¿el que instala puede enterarse
    de esto leyendo la referencia?», y una variable comentada NO llega a la página.
    Aceptar `#` también convertía en «declarada» cualquier línea de PROSA que
    empezara con `VAR=` (`.env.example:93` es una frase que arranca con
    `BASA_PURGE_ENABLED=false`).

    Estrechar este conjunto no puede romper CI: las MENTIRAS son
    `declaradas - código`, así que quitar elementos de `declaradas` sólo puede
    sacar mentiras, nunca agregarlas. Lo que sí crece son los HUECOS, que es
    justo el trabajo pendiente que estaba oculto.
    """
    if not ENV_EXAMPLE.exists():
        raise InsumoAusenteError(f"falta {ENV_EXAMPLE.relative_to(REPO)} — el eje de config no puede comparar")
    return {
        m.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (m := re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip()))
    }


# ── eje C · contratos de error ───────────────────────────────────────────────────
def contratos_del_codigo() -> set[str]:
    encontrados: set[str] = set()
    for py in BACKEND_SRC.rglob("*.py"):
        try:
            arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                if nodo.value in CONTRACT_NO_ES_ESTADO:
                    continue
                if CONTRACT_RE.match(nodo.value) or nodo.value in ESTADOS_LICENCIA:
                    encontrados.add(nodo.value)
    return encontrados


def contratos_documentados() -> set[str]:
    texto = "\n".join(
        md.read_text(encoding="utf-8", errors="replace")
        for md in DOCS_PRODUCTO.rglob("*.md")
    )
    return {lit for lit in contratos_del_codigo() if lit in texto}


# ── veredicto ────────────────────────────────────────────────────────────────────
def construir_veredicto() -> dict:
    codigo_rutas, contrato_rutas = rutas_del_codigo(), rutas_del_contrato()
    codigo_env, declaradas_env = env_del_codigo(), env_declaradas()
    codigo_lits = contratos_del_codigo()
    documentados_lits = contratos_documentados()

    hallazgos: list[dict] = []

    def anotar(eje: str, categoria: str, item: str, detalle: str) -> None:
        hallazgos.append({"eje": eje, "categoria": categoria, "item": item, "detalle": detalle})

    for ruta in sorted(contrato_rutas.keys() - codigo_rutas.keys()):
        anotar("rutas", "documentado_no_existe", ruta,
               "está en el openapi publicado y ningún decorador del backend la declara")
    for ruta in sorted(codigo_rutas.keys() - contrato_rutas.keys()):
        verbos = ",".join(sorted(codigo_rutas[ruta]))
        anotar("rutas", "existe_no_documentado", f"{verbos} {ruta}",
               "el backend la sirve y no aparece en el openapi publicado")

    for var in sorted(declaradas_env - codigo_env.keys()):
        anotar("config", "documentado_no_existe", var,
               "declarada en .env.example y ningún plano la consume (ni código, ni motor, ni compose)")
    for var in sorted(k for k, o in codigo_env.items() if o == "app") :
        if var not in declaradas_env:
            anotar("config", "existe_no_documentado", var,
                   "el producto la lee y no está en .env.example — invisible para la referencia generada")
    for var in sorted(k for k, o in codigo_env.items() if o == "orquestacion"):
        if var not in declaradas_env:
            anotar("orquestacion", "solo_compose", var,
                   "perilla del compose con default; no es superficie de configuración del producto")

    for lit in sorted(codigo_lits - documentados_lits):
        anotar("contratos", "existe_no_documentado", lit,
               "el código lo emite como estado y docs/docs no lo menciona")

    resumen = {
        cat: sum(1 for h in hallazgos if h["categoria"] == cat)
        for cat in ("documentado_no_existe", "existe_no_documentado", "solo_compose")
    }
    return {
        "veredicto": "FAIL" if resumen["documentado_no_existe"] else "PASS",
        "resumen": resumen,
        "medido": {
            "rutas_codigo": len(codigo_rutas),
            "rutas_openapi": len(contrato_rutas),
            "env_codigo": len(codigo_env),
            "env_declaradas": len(declaradas_env),
            "contratos_codigo": len(codigo_lits),
            "contratos_documentados": len(documentados_lits),
        },
        "hallazgos": hallazgos,
    }


def imprimir(v: dict) -> None:
    m = v["medido"]
    print(f"\nGATE DE DRIFT DOC ↔ CÓDIGO — {v['veredicto']}\n")
    print("| Eje | Código | Doc | Δ |")
    print("|---|---|---|---|")
    print(f"| rutas | {m['rutas_codigo']} | {m['rutas_openapi']} | {m['rutas_codigo'] - m['rutas_openapi']:+d} |")
    print(f"| config | {m['env_codigo']} | {m['env_declaradas']} | {m['env_codigo'] - m['env_declaradas']:+d} |")
    print(f"| contratos | {m['contratos_codigo']} | {m['contratos_documentados']} | "
          f"{m['contratos_codigo'] - m['contratos_documentados']:+d} |")

    for categoria, titulo in (
        ("documentado_no_existe", "MENTIRAS — la doc lo promete y el código no lo tiene"),
        ("existe_no_documentado", "HUECOS — el código lo hace y nadie lo escribió"),
        ("solo_compose", "ORQUESTACIÓN — informativo, no cuenta como hueco"),
    ):
        items = [h for h in v["hallazgos"] if h["categoria"] == categoria]
        print(f"\n{titulo}: {len(items)}")
        for h in items:
            print(f"  [{h['eje']}] {h['item']} — {h['detalle']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate de drift doc ↔ código")
    ap.add_argument("--json", metavar="RUTA", help="escribe el veredicto como JSON")
    args = ap.parse_args()

    try:
        v = construir_veredicto()
    except InsumoAusenteError as exc:
        print(f"❌ GATE DE DRIFT — no pudo correr: {exc}", file=sys.stderr)
        return 1

    imprimir(v)
    if args.json:
        Path(args.json).write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\n→ veredicto en {args.json}")
    return 1 if v["resumen"]["documentado_no_existe"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
