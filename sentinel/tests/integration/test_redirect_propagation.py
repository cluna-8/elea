"""Propagación de un cambio de destino < 60 s (T050; SC-009).

«Cambiar el destino de un alias surte efecto para todos los usuarios del alcance, sin tocar ningún equipo, en
menos de un minuto.» La política se lee por pedido desde un snapshot por tenant (`RedirectStore`); lo que
acota la propagación es esa caché:

1. con Redis, la escritura sube una **versión compartida** que cada proceso compara en cada lectura ⇒ el
   cambio vale en el SIGUIENTE pedido de cualquier worker;
2. sin Redis (o si publicar la versión falla) rige el TTL de la caché local (`REDIRECT_CACHE_TTL_S`, default
   5 s) ⇒ el cambio vale en cuanto vence, y el default queda muy por debajo de 60 s;
3. el motor no guarda nada de la política: la autorización va firmada en cada pedido, así que el destino que
   el guard ve es el de la resolución de ese pedido.

También ata a FR-034: al cambiar el destino cambia el `namespace` de caché de respuestas del motor, así que
una respuesta del destino anterior no se sirve tras el cambio.

Pasarela y guard reales con loader en memoria y un Redis falso compartido; sin Docker ni Postgres.
"""
import json
from dataclasses import replace

import pytest

from sentinel.engine import redirect_guard as guard
from sentinel.redirect import authz
from sentinel.redirect.plugin import RedirectPlugin
from sentinel.redirect.store import DEFAULT_TTL, RedirectStore
from sentinel.tests import redirect_fixtures as fx

SC009_SECONDS = 60
DEST_B = {**fx.DEST_CHAT, "id": "d-chat-b", "name": "Qwen UE (b)", "real_model": "otro-modelo"}
BODY = {"model": "pro", "messages": [{"role": "user", "content": "hola"}]}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.delenv("REDIRECT_CACHE_TTL_S", raising=False)


def snap(target):
    """Snapshot con dos destinos de chat; la regla del alias `pro` apunta a `target`."""
    s = fx.snapshot("on", targets=(target,))
    return replace(s, destinations={**s.destinations, DEST_B["id"]: DEST_B},
                   credentials={**s.credentials, DEST_B["id"]: json.dumps({"api_key": "sk-destino-b"})})


class Db:
    """«Base de datos» compartida por los workers: lo que escribe el admin lo lee cualquiera."""
    def __init__(self):
        self.target = "d-chat"

    def load(self, tenant):
        return snap(self.target)


class FakeRedis:
    """Lo que usa el store: `mget` de las dos claves de versión e `incr`."""
    def __init__(self):
        self.kv, self.down = {}, False

    def mget(self, *keys):
        if self.down:
            raise ConnectionError("redis caído")
        return [self.kv.get(k) for k in keys]

    def incr(self, key):
        if self.down:
            raise ConnectionError("redis caído")
        self.kv[key] = int(self.kv.get(key) or 0) + 1


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def worker(db, redis, clock, *, ttl=None):
    store = RedirectStore(loader=db.load, ttl=ttl, key_models=lambda k: None,
                          redis_factory=lambda: redis, decrypt=lambda blob: json.loads(blob) if blob else {},
                          clock=clock)
    return RedirectPlugin(store=store), store


async def served(plugin):
    """Destino con el que la pasarela firma el pedido de `pro` + el `cache` que fijaría el guard."""
    c = fx.ctx()
    assert await plugin.pre_request(c) is None
    out, headers = plugin.pre_engine(c, dict(BODY), {})
    grant = authz.verify(headers[authz.HEADER], expected_model=out["model"])
    data = {**out, "proxy_server_request": {"headers": dict(headers)},
            "metadata": {"masking_report": {"completed": True, "degraded": False, "detected": 0, "masked": 0}}}
    return grant.destination_id, out["model"], guard.apply_redirect(data, environ={})["cache"]["namespace"]


# ── con Redis: el siguiente pedido de cualquier worker ───────────────────────

async def test_con_redis_el_cambio_vale_en_el_siguiente_pedido_de_todos_los_workers():
    db, redis, clock = Db(), FakeRedis(), Clock()
    (a, store_a), (b, _) = worker(db, redis, clock), worker(db, redis, clock)
    assert (await served(a))[0] == (await served(b))[0] == "d-chat"          # ambos tienen la política cacheada
    db.target = "d-chat-b"                                                   # el admin cambia el destino…
    store_a.bump(fx.TENANT)                                                  # …y la API de admin hace `_bump`
    # sin que pase el tiempo (< 1 s), los DOS workers ya sirven por el destino nuevo
    assert (await served(a))[0] == "d-chat-b"
    assert (await served(b))[0] == "d-chat-b"


async def test_un_cambio_de_instalacion_llega_a_todos_los_tenants():
    db, redis, clock = Db(), FakeRedis(), Clock()
    (a, store_a), (b, _) = worker(db, redis, clock), worker(db, redis, clock)
    await served(a), await served(b)
    db.target = "d-chat-b"
    store_a.bump(None)                                                       # nivel instalación: versión global
    assert (await served(b))[0] == "d-chat-b"


async def test_sin_el_cambio_no_se_relee_la_base():
    db, redis, clock = Db(), FakeRedis(), Clock()
    loads = []
    real = db.load
    db.load = lambda t: (loads.append(t), real(t))[1]
    a, _ = worker(db, redis, clock)
    for _ in range(5):
        await served(a)
    assert len(loads) == 1                                                   # la caché hace su trabajo hasta que cambia la versión


# ── sin Redis: rige el TTL, y es muy menor que 60 s ──────────────────────────

def test_el_ttl_por_defecto_esta_muy_por_debajo_de_sc009():
    assert DEFAULT_TTL <= SC009_SECONDS / 10
    assert RedirectStore(loader=lambda t: None, key_models=lambda k: None, redis_factory=lambda: None).ttl == DEFAULT_TTL


async def test_sin_redis_el_cambio_vale_al_vencer_el_ttl():
    db, clock = Db(), Clock()
    a, _ = worker(db, None, clock)
    b, _ = worker(db, None, clock)
    await served(a), await served(b)
    db.target = "d-chat-b"                                                   # otro proceso lo escribió: este no recibe aviso
    clock.t += DEFAULT_TTL - 0.5
    assert (await served(b))[0] == "d-chat"                                  # todavía dentro del TTL: lo de antes
    clock.t += 0.5 + 0.01
    assert (await served(a))[0] == (await served(b))[0] == "d-chat-b"
    assert DEFAULT_TTL + 0.01 < SC009_SECONDS


async def test_si_redis_cae_o_no_publica_la_version_rige_el_ttl():
    db, redis, clock = Db(), FakeRedis(), Clock()
    (a, store_a), (b, _) = worker(db, redis, clock), worker(db, redis, clock)
    await served(a), await served(b)
    redis.down = True                                                        # el cambio no se pudo publicar
    db.target = "d-chat-b"
    store_a.bump(fx.TENANT)                                                  # no propaga: el log lo dice, no rompe
    clock.t += DEFAULT_TTL + 0.01
    assert (await served(b))[0] == "d-chat-b"
    assert (await served(a))[0] == "d-chat-b"


async def test_el_ttl_configurable_se_respeta(monkeypatch):
    monkeypatch.setenv("REDIRECT_CACHE_TTL_S", "20")
    db, clock = Db(), Clock()
    a, store_a = worker(db, None, clock)
    assert store_a.ttl == 20.0 and store_a.ttl < SC009_SECONDS
    await served(a)
    db.target = "d-chat-b"
    clock.t += 20.01
    assert (await served(a))[0] == "d-chat-b"


# ── el motor no retiene la política; la caché de respuestas no cruza el cambio ─

async def test_el_pedido_siguiente_lleva_el_destino_nuevo_hasta_el_guard_y_otro_namespace_de_cache():
    db, redis, clock = Db(), FakeRedis(), Clock()
    a, store_a = worker(db, redis, clock)
    dest_1, model_1, ns_1 = await served(a)
    db.target = "d-chat-b"
    store_a.bump(fx.TENANT)
    dest_2, model_2, ns_2 = await served(a)
    assert (dest_1, dest_2) == ("d-chat", "d-chat-b")
    assert model_1 == "rdx-chatcompat/qwen-destino" and model_2 == "rdx-chatcompat/otro-modelo"
    assert ns_1 != ns_2                                                      # FR-034: nada del destino anterior se sirve
    db.target = "d-chat"
    store_a.bump(fx.TENANT)
    assert (await served(a))[2] == ns_1                                      # y si vuelve, vuelve a su propia caché


def test_la_autorizacion_del_pedido_vence_mucho_antes_que_sc009():
    """Lo único que decide el destino en el motor es la autorización firmada de ESE pedido: no hay política
    cacheada allí, y la firma misma vence en segundos."""
    assert authz.DEFAULT_TTL <= SC009_SECONDS / 2
