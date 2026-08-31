#!/usr/bin/env bash
# issue #151 (decisiones ② y ③ del #134, selladas por JF el 12-ago — ver ADR-0003): los
# LÍMITES DEL MOTOR sobre el runtime local, y que la imagen pinneada de verdad los honre.
#
# Son el segundo y el tercer candado del nodo C1. El primero es el tope de admisión del
# backend; éstos existen para que la cola infinita del 30-jul no vuelva a existir NI AUNQUE
# el backend falle en cortarla —byok por `/gw`, un worker de más, un perfil con el tope mal
# girado—, porque el runtime local serializa las generaciones y encola FIFO sin límite:
#
#   · `max_parallel_requests: 20` — techo de generaciones en vuelo contra ese upstream. 20 =
#     total del backend (8 por proceso × 2 workers = 16) + margen, POR ENCIMA a propósito: el
#     que tiene que rechazar es el backend, con su 503 honesto, auditado y con cabecera
#     `X-Sentinel-Rejected` — no el motor, con un error opaco que nadie cuenta.
#   · `num_retries: 0` — los reintentos globales (2, sanos contra un proveedor cloud) contra
#     una cola que serializa son ×3 trabajo por pedido en el peor momento. Amplificación, no
#     resiliencia.
#
# Dos mitades, y las dos hacen falta:
#
#   (a) ESTÁTICA — todo deployment conversable del runtime local (`ollama_chat/`) declara los
#       dos valores, en el catálogo de dev y en las plantillas de perfil que se rinden para
#       las sedes. El contract test del backend
#       (tests/contract/test_catalogo_motor_paralelismo.py) cubre el catálogo de dev y la
#       relación con el tope del backend, pero su contenedor NO ve deploy/clients/: sin esta
#       mitad, la sede —el sitio donde ocurrió el incidente— quedaría sin candados y verde.
#
#   (b) VIVA — la imagen pinneada convierte esas claves en comportamiento REAL. Ninguna de las
#       dos es un campo declarado del modelo de parámetros del motor: viajan con el deployment
#       y las consume el router (una construye un semáforo, la otra pisa el `num_retries`
#       global al fallar). O sea que un typo, un rename upstream o un bump de imagen las
#       dejarían pasar SIN error y sin efecto — límites que son comentarios. Por eso se
#       levanta la imagen y se le pregunta al router qué construyó y cuántas veces reintenta.
#
# Escotilla documentada: SENTINEL_SKIP_ENGINE_IMAGE_INTROSPECTION=1 omite (b) —y sólo (b)— para
# entornos sin acceso al registry. Se anuncia en la salida: un gate que se degrada en silencio
# no es un gate.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

TOPE=20          # max_parallel_requests del deployment local (#151)
REINTENTOS=0     # num_retries del deployment local (#134-②)
# Digest de la imagen del motor contra la que se verificó (b): litellm 1.92.0, el mismo pin
# del docker-compose.yml. Se repite acá para que un bump ponga esto en ROJO y obligue a
# re-verificar el comportamiento en la versión nueva — que es exactamente el proceso de bump
# que documenta el compose ("cambiar el digest → correr los contract tests").
DIGEST_VERIFICADO="sha256:80ea654c506da9083503d00c1b323b2fecddf17af6add9bf01b2603938e17bd2"
VERSION_VERIFICADA="1.92."

fail=0
error() { echo "❌ $1"; fail=1; }

# ── (a) los dos límites están declarados en todo catálogo que hable con el runtime local ───
# Se recorre cada item del `model_list` (bloque `- litellm_params:` hasta el próximo item o
# clave de nivel 0) y se exigen SÓLO en los conversables. Las embeddings del auto-router
# (`ollama/`) quedan fuera a propósito: sale una por chat y los chats ya vienen acotados por
# el gate del backend, así que ni el techo quitaría cola ni el reintento la amplifica — y
# apagarles el reintento sí agregaría un modo de degradación nuevo al ruteo.
revisar_catalogo() {
    local fichero="$1" salida vistos
    [ -f "$fichero" ] || return 0
    salida="$(awk -v tope="$TOPE" -v reint="$REINTENTOS" '
        function cerrar() {
            if (bloque != "" && bloque ~ /model: *ollama_chat\//) {
                vistos++
                etiqueta = (alias == "" ? "(alias no leído)" : alias)
                if (bloque !~ ("max_parallel_requests: *" tope "([^0-9]|$)"))
                    print "FALTA max_parallel_requests: " tope " || " etiqueta
                if (bloque !~ ("num_retries: *" reint "([^0-9]|$)"))
                    print "FALTA num_retries: " reint " || " etiqueta
            }
            bloque = ""; alias = ""
        }
        /^- litellm_params:[[:space:]]*$/ { cerrar(); dentro = 1; next }
        /^[^[:space:]]/ && dentro && !/^- litellm_params:/ { cerrar(); dentro = 0 }
        dentro {
            bloque = bloque "\n" $0
            if ($1 == "model_name:") alias = $2
        }
        END { cerrar(); print "VISTOS " vistos + 0 }
    ' "$fichero")"
    vistos="$(awk '/^VISTOS /{print $2}' <<<"$salida")"
    while IFS= read -r linea; do
        [ -n "$linea" ] || continue
        local clave alias
        clave="${linea%% ||*}"; clave="${clave#FALTA }"
        alias="${linea##*|| }"
        error "$(basename "$fichero"): el deployment local '$alias' no declara '$clave'.
   El runtime local serializa y encola FIFO sin tope: sin ese límite vuelve a ser posible la
   cola que dejó el producto mudo ~10 min en la sede (30-jul)."
    done < <(grep '^FALTA ' <<<"$salida" || true)
    echo "   · $(basename "$(dirname "$fichero")")/$(basename "$fichero"): $vistos deployment(s) local(es)"
}

CATALOGOS=("$REPO_ROOT/litellm/config.yaml")
while IFS= read -r tmpl; do CATALOGOS+=("$tmpl"); done < <(
    find "$REPO_ROOT/deploy/clients" -name 'config.yaml.tmpl' | sort)

echo "Catálogos del motor revisados:"
for cat in "${CATALOGOS[@]}"; do revisar_catalogo "$cat"; done

# Guarda anti-verde-por-casualidad: al menos un deployment local tiene que existir en algún
# catálogo. Si el prefijo cambia o el parser se rompe, arriba no se mira NADA y todo pasa.
locales_totales=0
for cat in "${CATALOGOS[@]}"; do
    locales_totales=$(( locales_totales + $(grep -c 'model: ollama_chat/' "$cat" || true) ))
done
[ "$locales_totales" -gt 0 ] || error "ningún deployment 'ollama_chat/' en ningún catálogo:
   o cambió la forma del config, o este check dejó de mirar lo que dice mirar"

# ── (b) la imagen pinneada honra las dos claves (contract test contra el motor real) ───────
# `[[:space:]]` y no `\s`: el `sed -E` de BSD (macOS, donde también se corren estos gates)
# no conoce la abreviatura de GNU y devolvía vacío en silencio.
IMAGEN="$(sed -nE 's#^[[:space:]]*image:[[:space:]]*(ghcr\.io/berriai/litellm:[^[:space:]]+)[[:space:]]*$#\1#p' \
    "$REPO_ROOT/docker-compose.yml" | head -1)"
[ -n "$IMAGEN" ] || error "no encuentro la imagen pinneada del motor en docker-compose.yml"

case "$IMAGEN" in
    ""|*"$DIGEST_VERIFICADO") ;;
    *) error "la imagen del motor cambió de digest respecto de la verificada acá.
   Pinneada:   $IMAGEN
   Verificada: ...@$DIGEST_VERIFICADO (litellm ${VERSION_VERIFICADA}x)
   Los dos límites viajan como parámetros del deployment, así que un rename upstream no da
   error: los deja sin efecto en silencio. Re-correr la introspección de abajo contra la
   imagen nueva y actualizar DIGEST_VERIFICADO si sigue comportándose igual." ;;
esac

if [ "${SENTINEL_SKIP_ENGINE_IMAGE_INTROSPECTION:-0}" = "1" ]; then
    echo "⚠️  introspección de la imagen OMITIDA por SENTINEL_SKIP_ENGINE_IMAGE_INTROSPECTION=1
   (queda verificada sólo la parte estática; el pin por digest sigue vigilado)"
elif [ -n "$IMAGEN" ]; then
    if ! command -v docker >/dev/null 2>&1; then
        error "docker no está disponible: la introspección de la imagen del motor no se puede
   omitir sin decirlo (SENTINEL_SKIP_ENGINE_IMAGE_INTROSPECTION=1)"
    elif ! docker image inspect "$IMAGEN" >/dev/null 2>&1 && ! docker pull -q "$IMAGEN" >/dev/null 2>&1; then
        error "no pude obtener la imagen pinneada del motor ($IMAGEN)"
    else
        # Se le pregunta al ROUTER, no al parser de config: lo que importa no es que las
        # claves se acepten (se acepta cualquier extra), sino que UNA se convierta en el
        # semáforo que acota las generaciones en vuelo y la OTRA en un único intento. El
        # upstream se dobla con una función que cuenta llamadas y falla: no hay red, no hay
        # modelo y el número de intentos es observable.
        salida="$(docker run --rm --entrypoint python "$IMAGEN" -c "
import asyncio
from importlib.metadata import version
import litellm
from litellm import Router
from litellm.exceptions import APIConnectionError

PARAMS = {'model': 'ollama_chat/sonda', 'api_base': 'http://127.0.0.1:11434',
          'max_parallel_requests': $TOPE, 'num_retries': $REINTENTOS}

r = Router(model_list=[{'model_name': 'sonda-local', 'litellm_params': dict(PARAMS)}],
           num_retries=2)
sem = r._get_client(deployment=r.model_list[0], kwargs={}, client_type='max_parallel_requests')

intentos = {'n': 0}
async def upstream_caido(*a, **k):
    intentos['n'] += 1
    raise APIConnectionError(message='sonda', llm_provider='ollama_chat', model='sonda')
litellm.acompletion = upstream_caido
try:
    asyncio.run(r.acompletion(model='sonda-local', messages=[{'role': 'user', 'content': 'x'}]))
except Exception:
    pass

print('RESULTADO', version('litellm'), type(sem).__name__,
      getattr(sem, '_value', 'sin-valor'), intentos['n'])
" 2>/dev/null | grep '^RESULTADO ' || true)"
        read -r _ version tipo valor intentos <<<"${salida:-}"
        if [ "$tipo" != "Semaphore" ] || [ "$valor" != "$TOPE" ]; then
            error "la imagen pinneada NO construye el techo de paralelismo: esperaba
   Semaphore($TOPE) y obtuve '${tipo:-nada}(${valor:-nada})'. El max_parallel_requests del
   catálogo sería un comentario, no un límite."
        fi
        # Un intento y ninguno más: con el global en 2 y sin esta clave serían 3.
        if [ "${intentos:-}" != "1" ]; then
            error "la imagen pinneada NO respeta el num_retries del deployment: el upstream
   caído se llamó ${intentos:-?} vez/veces, esperaba 1. Los reintentos globales seguirían
   amplificando ×3 la cola del runtime local (#134-②)."
        fi
        case "${version:-}" in
            "$VERSION_VERIFICADA"*)
                echo "   · motor $version: max_parallel_requests → Semaphore($valor) ✔ · num_retries → $intentos intento ✔" ;;
            *) error "la imagen reporta litellm ${version:-?}, no la línea ${VERSION_VERIFICADA}x
   verificada — revisar el pin y re-verificar el comportamiento" ;;
        esac
    fi
fi

[ "$fail" = 0 ] && echo "✅ límites del runtime local OK: declarados en todo catálogo conversable
   y honrados por la imagen pinneada del motor (techo real + un solo intento)"
exit $fail
