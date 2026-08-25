"""El contrato de `encryption_service.encrypt` (issue #283).

El defecto de fondo que este contrato cierra: `encrypt()` devolvía `None` por DOS causas
—no hay Fernet, o el valor está vacío— y ese `None` era una señal de error **in-band** que
nada obligaba a mirar. De los tres callers del producto, dos no la miraban, y persistían el
`None`: el alta de guardián tiraba la credencial recién cargada con un 201 encima, y la
edición dejaba en NULL una credencial que **estaba funcionando**.

Estos tests fijan la separación en la raíz, que es lo que impide que un cuarto caller la
reintroduzca sin enterarse.
"""
import pytest

from src.services.encryption_service import CifradoNoDisponible, decrypt, encrypt


@pytest.fixture
def fernet_sano(monkeypatch):
    """La suite corre con el cifrado apagado (`conftest.py:29`), así que el camino feliz
    hay que prenderlo. Se parchea el `_fernet` del módulo y no el env: `encryption_service`
    lee `FERNET_SECRET_KEY` UNA vez en el import y setear la variable acá no haría nada."""
    from cryptography.fernet import Fernet
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", Fernet(Fernet.generate_key()))
    yield


@pytest.fixture
def fernet_caido(monkeypatch):
    """`FERNET_SECRET_KEY` ausente, vacía o **inválida** — los tres dejan `_fernet` en None.

    La tercera es la que llega a producción: el compose exige la variable con
    `${FERNET_SECRET_KEY:?...}`, guard que corta con ausente o vacía pero acepta cualquier
    cadena no vacía. Una clave con el formato equivocado lo pasa, `Fernet(...)` levanta en el
    import y queda un warning en el arranque. El guard del compose es de FORMA; la VALIDEZ
    sólo se comprueba acá."""
    from src.services import encryption_service
    monkeypatch.setattr(encryption_service, "_fernet", None)
    yield


def test_sin_cifrado_disponible_LEVANTA_en_vez_de_devolver_None(fernet_caido):
    """El corazón del #283: la causa grave propaga, no se puede ignorar por omisión."""
    with pytest.raises(CifradoNoDisponible):
        encrypt("sk-un-secreto-real")


def test_el_valor_VACIO_devuelve_None_sin_levantar(fernet_sano):
    """«No hay nada que cifrar» no es un fallo: es cómo los callers expresan «esta fila no
    lleva credencial». Si el vacío también levantara, el guard sería incapaz de distinguir
    un despliegue roto de un alta sin credencial, y cortaría las dos."""
    assert encrypt("") is None


def test_el_valor_VACIO_devuelve_None_TAMBIEN_sin_cifrado(fernet_caido):
    """El orden importa y queda pineado acá: primero se mira si hay algo que cifrar, y
    recién después si se puede. Al revés, un alta sin credencial fallaría con 503 en un
    despliegue con el Fernet roto — cortar de más se lee como fail-closed y no lo es."""
    assert encrypt("") is None


def test_con_cifrado_sano_el_secreto_vuelve_entero(fernet_sano):
    """El camino feliz medido de punta a punta: no alcanza con que salga algo distinto del
    original, tiene que volver el MISMO valor."""
    secreto = "sk-la-credencial-del-cliente"
    cifrado = encrypt(secreto)
    assert cifrado and cifrado != secreto
    assert decrypt(cifrado) == secreto


def test_decrypt_NO_levanta_sin_cifrado_y_eso_es_deliberado(fernet_caido):
    """La asimetría entre `encrypt` y `decrypt` es una decisión, no un olvido — este test
    está para que quien venga a «emparejarlas» lea el motivo antes de romperlo.

    El `None` de `decrypt` va en la dirección contraria: es la señal fail-closed del lado
    lectura. El gateway hace `token = decrypt(ref)` y sólo inyecta el `Authorization` si el
    token vino; sin él, el pedido sube SIN credencial y el upstream lo rechaza — nadie se
    sirve. Convertirlo en excepción cambiaría un camino que hoy degrada bien."""
    assert decrypt("gAAAAA-lo-que-sea") is None
