"""T001 (spec 033): el supervisor del motor valida ANTES de matar.

El invariante que sostienen estos tests: un `config.yaml` roto jamás deja el motor
caído. La mutación «validar DESPUÉS de matar» tiene que romperlos — por eso el test
del config inválido no se conforma con «0 relanzamientos» (un supervisor que mata y
después valida también da 0), sino que exige el **testigo positivo** de que el
proceso viejo sigue vivo y sin señales encima.

El supervisor vive en `<repo>/litellm/supervisor.py`, montado en el container del
backend como `/app/litellm_config` (docker-compose.yml:80) y agregado a `sys.path`
por `backend/tests/conftest.py:21-23` — mismo camino que `extensions`.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from supervisor import APPLYING, ERROR, IDLE, Supervisor  # noqa: E402

VALIDO = "model_list:\n  - model_name: gpt-4o\n"
ROTO = "model_list:\n  - model_name: [sin cerrar\n"


class FakeChild:
    """Proceso hijo falso: se muere cuando le mandan SIGTERM."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.alive = True
        self.terminated = False
        self.killed = False
        self.waits: list = []

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.alive = False
        return 0


class ChildTerco(FakeChild):
    """No se va con SIGTERM: obliga a agotar la ventana de drenaje y usar SIGKILL."""

    def terminate(self):
        self.terminated = True  # sigue vivo a propósito

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if not self.killed:
            raise subprocess.TimeoutExpired(cmd="litellm", timeout=timeout)
        return 0


class ChildQueCrashea(FakeChild):
    """Se muere SOLO, sin que nadie le mande una señal: OOM, segfault, exit(N).

    Es el caso que el `restart: unless-stopped` cubría cuando litellm era PID 1 y que
    dejó de cubrir cuando el supervisor pasó a ser el entrypoint.
    """

    CODIGO = 137  # 128+9: el OOM-killer, que es el caso real en la VM del cliente

    def __init__(self, n: int) -> None:
        super().__init__(n)
        self.alive = False

    def poll(self):
        return self.CODIGO


class Reloj:
    """Clock inyectable que sólo avanza cuando el test lo mueve."""

    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


@pytest.fixture
def entorno(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(VALIDO, encoding="utf-8")
    sentinel = tmp_path / "apply.trigger"
    status = tmp_path / "status"
    lanzados: list[FakeChild] = []

    def hacer(klass=FakeChild, **kw):
        def launch():
            c = klass(len(lanzados))
            lanzados.append(c)
            return c

        kw.setdefault("drain", 30.0)
        kw.setdefault("sleep", lambda _s: None)
        kw.setdefault("now", lambda: 1234.0)
        sup = Supervisor(
            config_path=cfg,
            sentinel_path=sentinel,
            status_dir=status,
            launch=launch,
            debounce=0.0,
            **kw,
        )
        sup.child = launch()  # el motor ya venía corriendo
        return sup

    return cfg, sentinel, status, lanzados, hacer


def _tocar(path, cuando):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    os.utime(path, (cuando, cuando))


def _estado(status_dir):
    import json

    return json.loads((status_dir / "status.json").read_text(encoding="utf-8"))


def test_config_valido_relanza_una_vez(entorno):
    cfg, _sentinel, status, lanzados, hacer = entorno
    sup = hacer()
    viejo = sup.child

    cfg.write_text(VALIDO + "  - model_name: gpt-5\n", encoding="utf-8")
    _tocar(cfg, 20000)

    assert sup.poll_once() is True
    assert len(lanzados) == 2, "tiene que haber exactamente UN relanzamiento"
    assert viejo.terminated is True
    assert _estado(status)["state"] == IDLE


def test_config_roto_no_toca_el_proceso_viejo(entorno):
    """El test que mata la mutación «validar después de matar»."""
    cfg, _sentinel, status, lanzados, hacer = entorno
    sup = hacer()
    viejo = sup.child

    cfg.write_text(ROTO, encoding="utf-8")
    _tocar(cfg, 20000)

    assert sup.poll_once() is False
    # negativo: no relanzó
    assert len(lanzados) == 1, "un config roto no puede relanzar el motor"
    # TESTIGO POSITIVO: el motor viejo sigue sirviendo y no recibió señal alguna.
    # Sin estos tres asserts, un supervisor que mata y DESPUÉS valida pasaría igual.
    assert viejo.alive is True, "el motor viejo tiene que seguir sirviendo"
    assert viejo.terminated is False, "no se le pudo haber mandado SIGTERM"
    assert viejo.killed is False, "no se le pudo haber mandado SIGKILL"
    est = _estado(status)
    assert est["state"] == ERROR
    assert "YAML inválido" in est["last_error"]


def test_rafaga_de_cambios_coalesce_en_un_solo_relanzamiento(entorno):
    """SC-003 a nivel unit."""
    cfg, _sentinel, _status, lanzados, hacer = entorno
    sup = hacer()

    for i, t in enumerate((20000, 20001, 20002)):
        cfg.write_text(VALIDO + f"  - model_name: extra-{i}\n", encoding="utf-8")
        _tocar(cfg, t)

    assert sup.poll_once() is True
    assert len(lanzados) == 2, "una ráfaga de 3 cambios tiene que dar UN relanzamiento"
    assert sup.poll_once() is False, "ya consumida la ráfaga, no queda trabajo pendiente"
    assert len(lanzados) == 2


def test_el_drenaje_espera_su_ventana_antes_del_sigkill(entorno):
    cfg, _sentinel, _status, lanzados, hacer = entorno
    sup = hacer(klass=ChildTerco, drain=30.0)
    viejo = sup.child

    cfg.write_text(VALIDO + "  - model_name: gpt-5\n", encoding="utf-8")
    _tocar(cfg, 20000)
    assert sup.poll_once() is True

    assert viejo.terminated is True, "primero SIGTERM"
    assert viejo.waits[0] == 30.0, "tiene que esperar la ventana de drenaje completa"
    assert viejo.killed is True, "recién después de la ventana, SIGKILL"
    assert len(lanzados) == 2


def test_autoreload_off_ignora_el_config_pero_obedece_el_sentinel(entorno):
    cfg, sentinel, _status, lanzados, hacer = entorno
    sup = hacer(autoreload=False)

    cfg.write_text(VALIDO + "  - model_name: gpt-5\n", encoding="utf-8")
    _tocar(cfg, 20000)
    assert sup.poll_once() is False, "con AUTORELOAD=off el mtime del config no dispara"
    assert len(lanzados) == 1

    _tocar(sentinel, 20001)
    assert sup.poll_once() is True, "el botón (sentinel) sigue disparando"
    assert len(lanzados) == 2


# ── Liveness del hijo (P1 del gate de #301) ──────────────────────────────────────────────
# El supervisor de entrypoint convierte a litellm en HIJO: PID 1 pasa a ser el supervisor.
# `restart: unless-stopped` (compose.prod.yml:171) recuperaba el motor porque su crash mataba
# PID 1 y el contenedor salía. Con el padre vivo el contenedor sigue `Up` y esa política no
# dispara nunca. Estos tests fijan que la recuperación vive ahora adentro del supervisor.


def test_el_motor_que_muere_solo_se_relanza(entorno):
    """El testigo del P1. Sin cambio de config: el ÚNICO disparador es la muerte del hijo."""
    _cfg, _sentinel, _status, lanzados, hacer = entorno
    sup = hacer(klass=ChildQueCrashea, relaunch_min=0.0)
    muerto = sup.child

    assert sup.check_liveness() is True, "un hijo muerto tiene que relanzarse"
    assert len(lanzados) == 2, "tiene que haber exactamente UN relanzamiento"
    assert sup.child is not muerto, "el supervisor tiene que quedarse con el hijo NUEVO"
    # Negativo que separa este camino del de recarga: a un proceso ya muerto no se le manda
    # SIGTERM ni SIGKILL. Si estos dos fueran True, estaríamos pasando por `_restart_child`.
    assert muerto.terminated is False
    assert muerto.killed is False


def test_run_vigila_la_muerte_del_hijo_y_no_solo_los_mtimes(entorno):
    """El test que FALLA contra el árbol sin el fix.

    Es el que importa: `check_liveness` podría existir y estar perfecto, y el motor quedar
    caído igual si el loop no lo llama. Acá no se toca el config — un `run()` que sólo vigila
    mtimes no relanza nada y el assert de abajo lo delata.
    """
    _cfg, _sentinel, status, lanzados, hacer = entorno
    sup = hacer(klass=ChildQueCrashea, relaunch_min=0.0)

    sup.run(interval=0.0, iterations=1)

    assert len(lanzados) == 2, (
        "el loop tiene que vigilar la liveness del hijo, no sólo el mtime del config: "
        "con el motor muerto y el config quieto, el contenedor sigue Up y `restart:` no dispara"
    )
    est = _estado(status)
    assert est["state"] == ERROR, "la muerte del motor tiene que quedar publicada"
    assert "137" in est["last_error"], f"el código de salida real tiene que viajar: {est}"


def test_un_motor_que_crashea_en_loop_no_forkea_una_vez_por_vuelta(entorno):
    """La cota de ritmo que reemplaza al backoff del daemon.

    `restart: unless-stopped` traía el backoff de Docker. Al mudar la recuperación adentro del
    supervisor, sin cota un motor que no arranca (credencial mala, puerto tomado) produciría un
    fork por vuelta del loop. El test fija que la cota EXISTE y que se libera con el tiempo, no
    su valor.
    """
    _cfg, _sentinel, _status, lanzados, hacer = entorno
    reloj = Reloj(1000.0)
    sup = hacer(klass=ChildQueCrashea, relaunch_min=5.0, now=reloj)

    # Tres vueltas del loop con el motor muerto en todas. El primer relanzamiento sale (el
    # hijo con el que arrancó no tiene fecha de nacimiento: no hay ventana que respetar);
    # los dos siguientes caen dentro de la ventana del que acaba de nacer.
    sup.run(interval=0.0, iterations=3)
    assert len(lanzados) == 2, "3 vueltas con el motor muerto no pueden dar 3 forks"

    reloj.avanzar(5.0)
    sup.run(interval=0.0, iterations=1)
    assert len(lanzados) == 3, "pasada la ventana, tiene que reintentar"


def test_la_recarga_normal_no_se_confunde_con_una_muerte_espontanea(entorno):
    """Brazo de control: con el hijo VIVO, `check_liveness` no hace absolutamente nada.

    Sin este test, un `check_liveness` que relanzara siempre pasaría los tres de arriba y
    reiniciaría el motor una vez por segundo en producción.
    """
    _cfg, _sentinel, _status, lanzados, hacer = entorno
    sup = hacer(relaunch_min=0.0)  # FakeChild arranca VIVO
    vivo = sup.child

    assert sup.check_liveness() is False
    assert len(lanzados) == 1, "un hijo vivo no se toca"
    assert sup.child is vivo
    assert vivo.terminated is False and vivo.killed is False


def test_un_salto_de_reloj_hacia_atras_no_traba_la_recuperacion(entorno):
    """P2-b del re-gate de #301: la cota se mide contra el reloj de PARED.

    `_now` no puede ser monotónico — alimenta también el `ts` de `status.json`, que el backend
    lee como epoch. Con reloj de pared, un step de NTP hacia atrás (o un resume de VM, o el
    restore de un snapshot) deja el delta NEGATIVO, y `delta < relaunch_min` seguiría siendo
    True hasta que el reloj vuelva a alcanzar `_last_launch`: la cota pensada para no forkear
    de más terminaría trabando la recuperación entera. Sin el clamp inferior este test falla.
    """
    _cfg, _sentinel, _status, lanzados, hacer = entorno
    reloj = Reloj(1000.0)
    sup = hacer(klass=ChildQueCrashea, relaunch_min=5.0, now=reloj)

    sup.run(interval=0.0, iterations=1)  # primer relanzamiento: el hijo nace con t=1000
    assert len(lanzados) == 2

    reloj.t = 100.0  # el reloj retrocede 15 minutos DESPUÉS de que el hijo nació
    sup.run(interval=0.0, iterations=1)

    assert len(lanzados) == 3, (
        "con el reloj atrasado el delta es negativo: el motor muerto tiene que relanzarse "
        "igual, no quedarse esperando a que el reloj alcance de nuevo a `_last_launch`"
    )


def test_la_muerte_se_publica_apenas_se_ve_aunque_la_cota_frene_el_relanzamiento(entorno):
    """P2-a del re-gate de #301: el primer crash tras un arranque sano no puede leerse `idle`.

    La cota frena el RELANZAMIENTO, no la publicación. Si el `status.json` se escribiera
    después del early-return, el motor caído se leería sano durante toda la ventana — y ese
    fichero es el único testigo que queda ahora que el contenedor se queda `Up`.
    """
    _cfg, _sentinel, status, lanzados, hacer = entorno
    reloj = Reloj(1000.0)
    sup = hacer(klass=ChildQueCrashea, relaunch_min=5.0, now=reloj)
    sup._spawn()  # el hijo nace acá: la cota queda activa
    sup._write_status(IDLE, config_hash="abc")  # ... y el estado publicado es el sano
    assert len(lanzados) == 2

    reloj.avanzar(1.0)  # el motor se muere 1 s después: DENTRO de la ventana de la cota
    assert sup.check_liveness() is False, "la cota tiene que frenar el relanzamiento"
    assert len(lanzados) == 2, "no puede haber relanzado dentro de la ventana"

    est = _estado(status)
    assert est["state"] == ERROR, f"un motor muerto no puede leerse `idle` ni un segundo: {est}"
    assert "137" in est["last_error"], f"el código de salida real tiene que viajar: {est}"


def test_la_muerte_del_hijo_nuevo_tambien_se_publica(entorno):
    """Mata la mutación «publicar una sola vez y nunca más».

    El flag que evita reescribir `status.json` una vez por vuelta durante la ventana tiene que
    resetearse cuando nace el hijo nuevo. Si no, la SEGUNDA muerte entra en silencio: el estado
    se queda con lo último que haya escrito un apply exitoso, que es `idle`.
    """
    _cfg, _sentinel, status, lanzados, hacer = entorno
    reloj = Reloj(1000.0)
    sup = hacer(klass=ChildQueCrashea, relaunch_min=5.0, now=reloj)

    sup.run(interval=0.0, iterations=1)  # ve la 1ª muerte, la publica y relanza
    assert len(lanzados) == 2
    sup._write_status(IDLE, config_hash="abc")  # un apply exitoso deja el estado sano

    reloj.avanzar(1.0)  # el hijo NUEVO también se muere, otra vez dentro de la ventana
    assert sup.check_liveness() is False
    assert _estado(status)["state"] == ERROR, "la muerte del hijo nuevo también tiene que publicarse"


def test_el_supervisor_nunca_escribe_en_el_volumen_del_config(entorno):
    """Su lado de `litellm_config` es `:ro` — sólo puede escribir en engine_status."""
    cfg, sentinel, status, _lanzados, hacer = entorno
    sup = hacer()
    antes = sorted(p.name for p in cfg.parent.iterdir())

    cfg.write_text(VALIDO + "  - model_name: gpt-5\n", encoding="utf-8")
    _tocar(cfg, 20000)
    sup.poll_once()

    despues = sorted(p.name for p in cfg.parent.iterdir() if p.name != "status")
    assert despues == antes, "el supervisor no puede crear ni borrar nada en litellm_config"
    assert (status / "status.json").exists()
