"""La ventana horaria de la purga (spec 018, FR-001 — `purger.en_ventana`).

La ventana es lo que sostiene SC-003: el purgador toca la tabla más caliente del producto sólo
de madrugada, así que la corrida no le cuesta el examen de carga a nadie. Una ventana mal
interpretada tiene dos formas de fallar y las dos son caras:

* **abre de más** — el `DELETE` por lotes compite con la vitrina, analytics y el export en
  horario de oficina;
* **abre de menos** (o nunca) — la retención deja de existir en silencio, que es el modo de
  falla que la 018 vino a cerrar.

Por eso lo que se mide acá no es «parsea el string», es el huso y los bordes: «las 02:00» de un
operador de Madrid no son las 02:00 del contenedor, que corre en UTC, y en España la diferencia
cambia con el horario de verano. El test usa una fecha de agosto y una de enero a propósito.
"""
import logging
from datetime import datetime, timedelta, timezone

from src.services.retention import purger

# Dos instantes UTC con la MISMA hora de reloj y distinto desfase en Madrid: en agosto CEST es
# UTC+2 y en enero CET es UTC+1. Es lo que hace que un purgador que ignore el huso (o que lo
# hornee como «+1») se ponga rojo en una de las dos.
AGOSTO_UTC = datetime(2026, 8, 14, 1, 30)    # 03:30 en Madrid → DENTRO de 02:00-05:00
ENERO_UTC = datetime(2026, 1, 14, 1, 30)     # 02:30 en Madrid → DENTRO
ENERO_TEMPRANO_UTC = datetime(2026, 1, 14, 0, 30)  # 01:30 en Madrid → FUERA


def test_la_ventana_por_default_se_lee_en_la_hora_de_la_instalacion():
    assert purger.en_ventana(AGOSTO_UTC) is True
    assert purger.en_ventana(ENERO_UTC) is True
    assert purger.en_ventana(ENERO_TEMPRANO_UTC) is False
    # La misma hora UTC que en agosto entra, en enero NO: es exactamente la hora que se corre
    # con el horario de verano (01:30 UTC son 03:30 en agosto y 02:30 en enero; 00:30 UTC son
    # 02:30 en agosto —dentro— y 01:30 en enero —fuera—).
    assert purger.en_ventana(AGOSTO_UTC - timedelta(hours=1)) is True
    assert purger.en_ventana(ENERO_UTC - timedelta(hours=1)) is False


def test_el_datetime_naive_se_lee_como_utc_y_el_aware_se_convierte():
    """El purgador le pasa el reloj de la DB, que es naive en UTC (`timezone('utc', now())`).

    Un naive leído como hora LOCAL DEL CONTENEDOR abriría la ventana con el desfase puesto, o
    sea a las 04:00 de Madrid en verano — y el operador vería la purga corriendo a una hora que
    no configuró.
    """
    naive = datetime(2026, 8, 14, 1, 30)
    aware = naive.replace(tzinfo=timezone.utc)
    assert purger.en_ventana(naive) == purger.en_ventana(aware) is True

    # El mismo instante escrito en otro huso tiene que dar lo mismo: lo que decide es el
    # INSTANTE, no cómo esté escrito.
    en_otro_huso = aware.astimezone(timezone(timedelta(hours=5)))
    assert purger.en_ventana(en_otro_huso) is True


def test_la_ventana_es_semiabierta_en_los_dos_extremos():
    """`[inicio, fin)`: así `23:00-02:00` y `02:00-05:00` no se pisan en la juntura.

    El borde importa de verdad para el scheduler: con los dos extremos cerrados, un tick que
    caiga justo en el minuto del cierre arrancaría una corrida entera fuera de la ventana.
    """
    en_utc = dict(ventana="02:00-05:00", tz="UTC")
    assert purger.en_ventana(datetime(2026, 8, 14, 1, 59), **en_utc) is False
    assert purger.en_ventana(datetime(2026, 8, 14, 2, 0), **en_utc) is True
    assert purger.en_ventana(datetime(2026, 8, 14, 4, 59), **en_utc) is True
    assert purger.en_ventana(datetime(2026, 8, 14, 5, 0), **en_utc) is False


def test_la_ventana_que_cruza_medianoche_es_valida():
    """`23:00-02:00` es la forma natural de decir «de madrugada» y hay que soportarla.

    Un parser ingenuo (`inicio <= t <= fin`) la deja SIEMPRE cerrada, que es la retención
    apagada en silencio.
    """
    de_noche = dict(ventana="23:00-02:00", tz="UTC")
    assert purger.en_ventana(datetime(2026, 8, 14, 23, 30), **de_noche) is True
    assert purger.en_ventana(datetime(2026, 8, 14, 0, 30), **de_noche) is True
    assert purger.en_ventana(datetime(2026, 8, 14, 2, 0), **de_noche) is False
    assert purger.en_ventana(datetime(2026, 8, 14, 12, 0), **de_noche) is False


def test_una_ventana_malformada_grita_y_cae_al_default(caplog):
    """Un typo no tumba el backend, pero tampoco pasa callado (criterio de `engine_gate`).

    Silencioso es lo peor de los tres finales posibles: el operador cree tener una ventana de
    madrugada, el purgador usa otra cosa, y no hay dónde verlo.
    """
    with caplog.at_level(logging.WARNING, logger="src.services.retention.purger"):
        # 03:30 en Madrid: dentro del DEFAULT, o sea que la respuesta prueba que cayó ahí.
        assert purger.en_ventana(AGOSTO_UTC, ventana="de 2 a 5") is True
    assert any("SENTINEL_PURGE_WINDOW" in r.getMessage() for r in caplog.records)


def test_una_ventana_de_ancho_cero_se_rechaza(caplog):
    """`03:00-03:00` no se puede leer sin adivinar, y las dos lecturas son caras.

    «Nunca» apaga la retención en silencio; «siempre» deja al purgador borrando a las once de la
    mañana contra la tabla más caliente del producto. Se trata como lo que es —una ventana
    inválida— y se cae al default con warning.
    """
    with caplog.at_level(logging.WARNING, logger="src.services.retention.purger"):
        assert purger.en_ventana(AGOSTO_UTC, ventana="03:00-03:00") is True
        assert purger.en_ventana(datetime(2026, 8, 14, 12, 0), ventana="03:00-03:00") is False
    assert any("SENTINEL_PURGE_WINDOW" in r.getMessage() for r in caplog.records)


def test_horas_fuera_de_rango_no_se_cuelan():
    """`25:00` y `02:99` son inválidas: sin el chequeo de rango entrarían como minutos del día
    y abrirían una ventana que el operador no escribió."""
    assert purger.en_ventana(AGOSTO_UTC, ventana="25:00-05:00") is True   # → default
    assert purger.en_ventana(AGOSTO_UTC, ventana="02:99-05:00") is True   # → default
    assert purger.en_ventana(datetime(2026, 8, 14, 12, 0), ventana="25:00-13:00") is False


def test_una_zona_desconocida_grita_y_cae_al_default(caplog):
    with caplog.at_level(logging.WARNING, logger="src.services.retention.purger"):
        assert purger.en_ventana(AGOSTO_UTC, tz="Marte/Olympus") is True
    assert any("SENTINEL_PURGE_WINDOW_TZ" in r.getMessage() for r in caplog.records)


def test_las_perillas_se_leen_del_entorno_cuando_no_se_pasan(monkeypatch):
    """El purgador llama a `en_ventana` sin argumentos: si las perillas no se leyeran del
    entorno, el operador configuraría una ventana que nadie mira."""
    monkeypatch.setenv("SENTINEL_PURGE_WINDOW", "10:00-11:00")
    monkeypatch.setenv("SENTINEL_PURGE_WINDOW_TZ", "UTC")
    assert purger.en_ventana(datetime(2026, 8, 14, 10, 30)) is True
    assert purger.en_ventana(datetime(2026, 8, 14, 11, 30)) is False
