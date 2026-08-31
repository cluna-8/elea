"""Tope de admisión al motor: envs acotadas + el semáforo que evita la inanición (nodo C1).

Lo que se fija acá es el MECANISMO, en dos mitades:

(a) **Las envs no pueden reinstalar el bug.** Un tope de `1e9` en vuelo, o un queue-timeout de
    600 s, son exactamente la cola infinita de la sede con otro nombre. Se prueba el helper
    (robustez) y además el CABLEADO de cada constante con la env REAL — sin lo segundo, un
    "simplificado" tipo `int(os.getenv(...) or 8)` pasaría el primero y dejaría entrar el
    absurdo. Mismo criterio y misma forma que `test_redis_degrade_hardening_105.py`, que es el
    patrón que selló el gate de #131.

(b) **El semáforo hace lo que promete**: deja entrar hasta el tope, hace esperar al que sobra,
    lo RECHAZA (no lo encola para siempre) al vencer el queue-timeout, libera el turno aunque
    el cuerpo reviente, y una sola adquisición cubre el reintento del mismo pedido.

Todo PURO: sin Postgres, sin app, sin motor.
"""
import asyncio
import importlib.util
from pathlib import Path

import pytest

from src.services import engine_gate


def _copia_del_modulo():
    """Ejecuta engine_gate.py de nuevo como módulo APARTE, sin registrarlo en `sys.modules`.

    Es la forma correcta de probar el cableado de las constantes acá, y no `importlib.reload`
    como en `test_redis_degrade_hardening_105`: aquel módulo sólo exporta floats, mientras que
    éste exporta además una CLASE (`EngineSaturatedError`). Un `reload` la reemplaza por otra
    clase con el mismo nombre, y a partir de ahí el `except EngineSaturatedError` de `chat.py`
    /`gateway.py` —que quedó apuntando a la clase vieja— deja de atrapar la nueva. O sea que el
    reload no "restaura" nada: envenena a todo test posterior que ejercite el rechazo (visto en
    vivo: el 503 de saturación se convertía en el 502 de "motor inalcanzable"). Con una copia
    aparte, el módulo real no se toca.
    """
    ruta = Path(engine_gate.__file__)
    spec = importlib.util.spec_from_file_location("engine_gate_copia_de_prueba", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ══════════════════════════════════════════════════════════════════════════════════════
# (a) Envs con guardia de rango
# ══════════════════════════════════════════════════════════════════════════════════════


def test_env_int_robusto_no_revienta_y_acota_el_rango(monkeypatch):
    """Ausente/vacío/malformado → default (un `int("")` al importar tumbaría el plano entero
    por un `- VAR=` de compose). Y parsear NO alcanza: un tope de 0 deja el producto sin chat y
    uno de 100000 es no tener tope — los dos caen al default."""
    monkeypatch.delenv("X_INT_TEST_C1", raising=False)
    assert engine_gate._env_int("X_INT_TEST_C1", 8, minimo=1, maximo=64) == 8
    for crudo in ("", "   ", "no-soy-int", "8.5", "1e9"):
        monkeypatch.setenv("X_INT_TEST_C1", crudo)
        assert engine_gate._env_int("X_INT_TEST_C1", 8, minimo=1, maximo=64) == 8, crudo
    for fuera in ("0", "-1", "65", "100000"):
        monkeypatch.setenv("X_INT_TEST_C1", fuera)
        assert engine_gate._env_int("X_INT_TEST_C1", 8, minimo=1, maximo=64) == 8, (
            f"{fuera!r} pasó crudo: un tope fuera de rango es no tener tope")
    monkeypatch.setenv("X_INT_TEST_C1", "16")
    assert engine_gate._env_int("X_INT_TEST_C1", 8, minimo=1, maximo=64) == 16


def test_env_float_robusto_no_revienta_y_acota_el_rango(monkeypatch):
    """Gemelo de `redis_client._env_float`: `inf`, `nan` y `1e400` parsean SIN error pero
    equivalen a no tener límite, que es el cuelgue que este módulo vino a matar."""
    monkeypatch.delenv("X_FLOAT_TEST_C1", raising=False)
    assert engine_gate._env_float("X_FLOAT_TEST_C1", 5.0, maximo=60.0) == 5.0
    for crudo in ("", "   ", "no-soy-float"):
        monkeypatch.setenv("X_FLOAT_TEST_C1", crudo)
        assert engine_gate._env_float("X_FLOAT_TEST_C1", 5.0, maximo=60.0) == 5.0, crudo
    for absurdo in ("inf", "nan", "Infinity", "1e400", "-1", "0", "1e9", "61"):
        monkeypatch.setenv("X_FLOAT_TEST_C1", absurdo)
        assert engine_gate._env_float("X_FLOAT_TEST_C1", 5.0, maximo=60.0) == 5.0, (
            f"{absurdo!r} pasó crudo — un timeout no finito, ≤0 o fuera de techo es no tener "
            "timeout")
    monkeypatch.setenv("X_FLOAT_TEST_C1", "2.5")
    assert engine_gate._env_float("X_FLOAT_TEST_C1", 5.0, maximo=60.0) == 2.5


@pytest.mark.parametrize("env,constante,default", [
    ("SENTINEL_ENGINE_MAX_CONCURRENCY", "ENGINE_MAX_CONCURRENCY", 8),
    ("SENTINEL_ENGINE_QUEUE_TIMEOUT_SECONDS", "ENGINE_QUEUE_TIMEOUT_SECONDS", 5.0),
    ("SENTINEL_ENGINE_TIMEOUT_SECONDS", "ENGINE_TIMEOUT_SECONDS", 60.0),
    ("SENTINEL_GW_BYOK_TIMEOUT_SECONDS", "GW_BYOK_TIMEOUT_SECONDS", 150.0),
    ("SENTINEL_GW_BYOK_READ_TIMEOUT_SECONDS", "GW_BYOK_READ_TIMEOUT_SECONDS", 150.0),
])
@pytest.mark.parametrize("valor_env", ["", "1e9"], ids=["vacio", "fuera-de-rango"])
def test_las_constantes_estan_cableadas_al_helper_con_guardia(
        monkeypatch, env, constante, default, valor_env):
    """El CABLEADO, con las envs reales y en sus dos propiedades (H2 del gate de #131):

    * env vacía ⇒ el import sobrevive y cae al default (un `float("")`/`int("")` reventaría el
      reload, o sea el arranque del worker, por un `- VAR=` en compose);
    * `"1e9"` ⇒ la guardia de RANGO se aplica sobre la constante. Un wiring "simplificado"
      (`int(os.getenv(...) or 8)`) sobrevive el caso vacío y deja pasar el 1e9 crudo — que es
      justo la mutación que reinstala la cola infinita.
    """
    with monkeypatch.context() as m:
        m.setenv(env, valor_env)
        copia = _copia_del_modulo()
    assert getattr(copia, constante) == default, (
        f"{constante} no pasa por el helper acotado — con {env}={valor_env!r} tendría "
        f"que caer al default {default}")


def test_con_la_env_valida_la_constante_la_toma(monkeypatch):
    """Contracara del anterior: la guardia acota, no ignora. Un valor razonable SÍ manda."""
    with monkeypatch.context() as m:
        m.setenv("SENTINEL_ENGINE_MAX_CONCURRENCY", "16")
        m.setenv("SENTINEL_ENGINE_QUEUE_TIMEOUT_SECONDS", "2.5")
        m.setenv("SENTINEL_ENGINE_TIMEOUT_SECONDS", "150")
        m.setenv("SENTINEL_GW_BYOK_TIMEOUT_SECONDS", "200")
        m.setenv("SENTINEL_GW_BYOK_READ_TIMEOUT_SECONDS", "200")
        copia = _copia_del_modulo()
    assert copia.ENGINE_MAX_CONCURRENCY == 16
    assert copia.ENGINE_QUEUE_TIMEOUT_SECONDS == 2.5
    assert copia.ENGINE_TIMEOUT_SECONDS == 150.0
    assert copia.GW_BYOK_TIMEOUT_SECONDS == 200.0
    assert copia.GW_BYOK_READ_TIMEOUT_SECONDS == 200.0


def test_el_byok_no_stream_tiene_su_propia_env_y_no_hereda_el_default_del_chat(monkeypatch):
    """H3 del gate de #135: los dos timeouts al motor son INDEPENDIENTES.

    Fusionarlos parecía economía y era una regresión silenciosa: el byok de `/gw` tenía `120.0`
    hardcodeado y pasaba a heredar el default 60 del chat, o sea que empezaba a cortar solo
    generaciones que antes servía —y encima con el trabajo del modelo ya pagado—. Son dominios
    distintos: el chat es una UI con una persona esperando, el byok es una coding tool. Que
    setear uno mueva al otro es exactamente el bug.
    """
    with monkeypatch.context() as m:
        m.setenv("SENTINEL_ENGINE_TIMEOUT_SECONDS", "30")
        m.delenv("SENTINEL_GW_BYOK_TIMEOUT_SECONDS", raising=False)
        copia = _copia_del_modulo()
    assert copia.ENGINE_TIMEOUT_SECONDS == 30.0
    assert copia.GW_BYOK_TIMEOUT_SECONDS == 150.0, (
        "el byok heredó el timeout del chat — esa es la regresión de H3")
    # El default tiene que SUPERAR los 120 s que el router del perfil prod espera por
    # generación: el que espera aguanta más que el que trabaja, o convierte una respuesta lenta
    # pero buena en un error nuestro.
    assert copia.GW_BYOK_TIMEOUT_SECONDS > 120.0


@pytest.mark.parametrize("queue_timeout,esperado", [
    ("5", "5"),        # el default histórico: el contrato con La ITV no se mueve
    ("20", "20"),
    ("2.4", "3"),      # segundos ENTEROS, y hacia arriba: nunca prometer antes de tiempo
    ("0.25", "1"),     # piso 1: un `Retry-After: 0` es "reintentá ya" = estampida
])
def test_el_retry_after_se_deriva_del_queue_timeout_real(monkeypatch, queue_timeout, esperado):
    """H9 del gate de #135: `Retry-After` decía "5" aunque la espera fuera configurable.

    El header promete «en tanto puede haber turno». Con un queue-timeout de 20 s, mandar a todos
    los clientes a reintentar a los 5 los devuelve en pleno pico — la estampida que el rechazo
    rápido vino a evitar.
    """
    with monkeypatch.context() as m:
        m.setenv("SENTINEL_ENGINE_QUEUE_TIMEOUT_SECONDS", queue_timeout)
        copia = _copia_del_modulo()
    assert copia.RETRY_AFTER_SATURATED == esperado


def test_el_estado_de_saturacion_no_matchea_el_filtro_canonico_de_bloqueos():
    """`rejected_saturated` NO puede empezar con `blocked`.

    El filtro canónico de compliance es `compliance_status LIKE 'blocked%'` y significa «el
    firewall impidió este pedido por política». Un rechazo por capacidad no lo impidió ninguna
    capa: contarlo ahí le mentiría al officer sobre cuántos intentos se bloquearon. Es una
    aserción de UNA línea y protege una decisión que se pierde en el próximo rename.
    """
    assert engine_gate.STATUS_SATURATED == "rejected_saturated"
    assert not engine_gate.STATUS_SATURATED.startswith("blocked")


def test_el_contrato_de_wire_del_rechazo_es_estable():
    """El harness de carga distingue NUESTRO 503 de uno de Caddy/proxy por esta cabecera."""
    assert engine_gate.HEADER_REJECTED == "X-Sentinel-Rejected"
    assert engine_gate.HEADER_REJECTED_SATURATED == "saturated"
    assert engine_gate.RETRY_AFTER_SATURATED == "5"


# ══════════════════════════════════════════════════════════════════════════════════════
# (b) El semáforo
# ══════════════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gate_chico(monkeypatch):
    """Tope 2 y queue-timeout corto, sobre un semáforo FRESCO del loop de este test.

    Se parchean las constantes y se fuerza la reconstrucción en vez de recargar el módulo:
    recargar dejaría a `chat.py`/`gateway.py` apuntando a los símbolos viejos, y lo que se
    prueba acá es el objeto que ellos usan.
    """
    monkeypatch.setattr(engine_gate, "ENGINE_MAX_CONCURRENCY", 2)
    monkeypatch.setattr(engine_gate, "ENGINE_QUEUE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(engine_gate, "_semaforo_actual", None)
    monkeypatch.setattr(engine_gate, "_loop_del_semaforo", None)
    yield
    engine_gate._semaforo_actual = None
    engine_gate._loop_del_semaforo = None


@pytest.mark.asyncio
async def test_hasta_el_tope_entran_y_el_que_sobra_espera(gate_chico):
    """Con cap=2: dos adentro, el tercero NO entra mientras los dos sigan dentro."""
    uno = await engine_gate.adquirir_turno().adquirir()
    dos = await engine_gate.adquirir_turno().adquirir()

    tercero = asyncio.create_task(engine_gate.adquirir_turno().adquirir())
    await asyncio.sleep(0.01)
    assert not tercero.done(), "el tercero entró con el tope lleno — el semáforo no gatea nada"

    uno.liberar()
    turno3 = await asyncio.wait_for(tercero, timeout=1.0)
    assert turno3.adquirido, "liberado un turno, el que esperaba tiene que entrar"

    dos.liberar()
    turno3.liberar()


@pytest.mark.asyncio
async def test_vencido_el_queue_timeout_se_rechaza_en_vez_de_encolar(gate_chico):
    """El corazón del fix: al vencer la espera NO se encola —se RECHAZA.

    Y se rechaza rápido: si tardara mucho más que el queue-timeout, el pedido seguiría
    reteniendo su conexión del pool, que es exactamente lo que hay que evitar.
    """
    dentro = [await engine_gate.adquirir_turno().adquirir() for _ in range(2)]
    try:
        inicio = asyncio.get_running_loop().time()
        with pytest.raises(engine_gate.EngineSaturatedError):
            await engine_gate.adquirir_turno().adquirir()
        esperado = asyncio.get_running_loop().time() - inicio
        assert esperado < 1.0, f"el rechazo tardó {esperado:.2f}s — tiene que ser rápido"
    finally:
        for turno in dentro:
            turno.liberar()


@pytest.mark.asyncio
async def test_el_rechazado_no_hereda_el_turno_que_se_libera_despues(gate_chico):
    """`wait_for` cancela el `acquire()` pendiente: el rechazado deja de ser waiter.

    Si quedara en la cola del semáforo, un turno liberado después se le "regalaría" a un pedido
    que ya recibió su 503 — y el permiso quedaría tomado por nadie, bajando el tope real.
    """
    uno = await engine_gate.adquirir_turno().adquirir()
    dos = await engine_gate.adquirir_turno().adquirir()

    with pytest.raises(engine_gate.EngineSaturatedError):
        await engine_gate.adquirir_turno().adquirir()

    uno.liberar()
    dos.liberar()

    # Los dos permisos están de vuelta y disponibles enteros.
    recuperados = [await engine_gate.adquirir_turno().adquirir() for _ in range(2)]
    assert all(t.adquirido for t in recuperados)
    for turno in recuperados:
        turno.liberar()


@pytest.mark.asyncio
async def test_el_turno_se_libera_aunque_el_cuerpo_reviente(gate_chico):
    """Un turno filtrado por un camino de error baja el tope de forma PERMANENTE hasta
    reiniciar el worker: peor que no tener tope, porque se degrada solo con el tiempo."""

    class _FalloDelMotor(Exception):
        pass

    for _ in range(3):  # varias veces: una fuga se acumularía y el 3.º no entraría
        with pytest.raises(_FalloDelMotor):
            async with engine_gate.adquirir_turno():
                raise _FalloDelMotor("el motor devolvió 500")

    # Con cap=2, si alguna de las 3 vueltas hubiera filtrado su turno, esto colgaría.
    libres = [await engine_gate.adquirir_turno().adquirir() for _ in range(2)]
    for turno in libres:
        turno.liberar()


@pytest.mark.asyncio
async def test_el_reintento_dentro_del_mismo_turno_no_readquiere(gate_chico):
    """UNA adquisición por pedido del usuario, aunque adentro haya dos llamadas al motor.

    Es la guardia de reversión del chat (spec 012 US6): el reintento es el MISMO pedido. Si
    re-adquiriera, con el tope lleno se rechazaría a sí mismo a mitad de camino, con la primera
    respuesta ya pagada.
    """
    ocupado = await engine_gate.adquirir_turno().adquirir()  # cap=2 ⇒ queda 1 libre
    try:
        llamadas = 0
        async with engine_gate.adquirir_turno():
            llamadas += 1                      # llamada al motor
            llamadas += 1                      # reintento de reversión, MISMO turno
            # Con el único permiso restante tomado por este bloque, un tercer pedido se rechaza:
            # prueba de que el reintento no consumió un permiso extra ni liberó el suyo.
            with pytest.raises(engine_gate.EngineSaturatedError):
                await engine_gate.adquirir_turno().adquirir()
        assert llamadas == 2
    finally:
        ocupado.liberar()


@pytest.mark.asyncio
async def test_liberar_dos_veces_no_regala_permisos(gate_chico):
    """`BoundedSemaphore` + flag: un `liberar()` de más no puede subir el tope en silencio."""
    turno = await engine_gate.adquirir_turno().adquirir()
    turno.liberar()
    turno.liberar()  # idempotente: ni levanta ni agranda el semáforo

    dentro = [await engine_gate.adquirir_turno().adquirir() for _ in range(2)]
    try:
        with pytest.raises(engine_gate.EngineSaturatedError):
            await engine_gate.adquirir_turno().adquirir()
    finally:
        for t in dentro:
            t.liberar()


@pytest.mark.asyncio
async def test_liberar_suelta_el_semaforo_que_dio_el_permiso_y_no_el_de_turno(gate_chico):
    """H5 del gate de #135: el turno recuerda SU semáforo, no vuelve a preguntar cuál es.

    Entre adquirir y liberar el semáforo del proceso puede rebindearse —el loop cambió (worker
    reiniciado, una suite que monta la app en otro loop) y `_semaforo()` reconstruye—. Soltando
    sobre el que devuelva `_semaforo()` en ese momento pasan las dos cosas malas a la vez: el
    semáforo NUEVO recibe un permiso que jamás entregó (con `BoundedSemaphore`, un `ValueError`
    que revienta el `finally` del stream y se lleva puesto el cierre del upstream) y el VIEJO
    se queda encogido para siempre.
    """
    turno = await engine_gate.adquirir_turno().adquirir()
    viejo = engine_gate._semaforo()
    assert viejo._value == 1, "cap=2 y un turno tomado"

    # Rebind: exactamente lo que hace `_semaforo()` cuando el loop cambió.
    engine_gate._semaforo_actual = None
    engine_gate._loop_del_semaforo = None
    nuevo = engine_gate._semaforo()
    assert nuevo is not viejo

    turno.liberar()  # sin la referencia guardada, acá saltaba `ValueError`

    assert viejo._value == 2, "el permiso tiene que volver al semáforo que lo dio"
    assert nuevo._value == 2, "y el semáforo nuevo no puede quedar inflado por un permiso ajeno"


@pytest.mark.asyncio
async def test_un_turno_no_adquirido_no_libera_nada(gate_chico):
    """`__aexit__` libera SÓLO si se adquirió: si el `adquirir()` falló por saturación, soltar
    igual le regalaría un permiso al semáforo (con `BoundedSemaphore`, un `ValueError`)."""
    turno = engine_gate.adquirir_turno()
    assert not turno.adquirido
    turno.liberar()  # no-op

    dentro = [await engine_gate.adquirir_turno().adquirir() for _ in range(2)]
    try:
        with pytest.raises(engine_gate.EngineSaturatedError):
            await engine_gate.adquirir_turno().adquirir()
    finally:
        for t in dentro:
            t.liberar()
