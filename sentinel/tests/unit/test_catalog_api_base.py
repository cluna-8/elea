"""`api_base` de las entradas de empresa (057 H1 del QA de T-B; Constitución III y Seguridad 4).

El motor llama a la `api_base` de la entrada con la credencial de la entrada: si el administrador de una empresa
pudiera apuntarla a la red interna de la instalación, el motor compartido sería un SSRF. Una entrada de **empresa**
exige una dirección https de un host público; se rechazan loopback, link-local (metadatos de nube), rangos privados,
nombres de servicio de la red de contenedores y los esquemas que no son http(s). Un interruptor de **instalación**
(`CATALOG_ALLOW_PRIVATE_API_BASE`, apagado) permite direcciones privadas y http para modelos locales on-prem, pero
nunca los metadatos de nube ni `file://`. Las entradas de instalación no pasan por esta regla.
"""
import pathlib

import pytest
import yaml

from sentinel.catalog import api_base as ab

ROOT = pathlib.Path(__file__).resolve().parents[3]

PUBLICAS = [
    "https://api.ejemplo.com/v1",
    "https://api.ejemplo.com:8443/v1/",
    "https://mi-recurso.openai.azure.com",
    "https://1.1.1.1/v1",
    "https://[2606:4700:4700::1111]/v1",
    "HTTPS://API.EJEMPLO.COM/v1",
]

# los seis casos de la prueba descartable del QA más las variantes de representación de una IP
INTERNAS = [
    "http://169.254.169.254/latest",
    "https://169.254.169.254/latest",
    "http://engine:4000/v1",
    "http://db:5432",
    "http://127.0.0.1:8000/api/v1/gw/v1",
    "file:///etc/passwd",
    "ftp://x",
    "https://localhost/v1",
    "https://LOCALHOST./v1",
    "https://app.localhost/v1",
    "https://10.0.0.5/v1",
    "https://172.16.0.1/v1",
    "https://192.168.1.10/v1",
    "https://100.64.0.1/v1",
    "https://0.0.0.0/v1",
    "https://224.0.0.1/v1",
    "https://240.0.0.1/v1",
    "https://[::1]/v1",
    "https://[::]/v1",
    "https://[fe80::1]/v1",
    "https://[fc00::1]/v1",
    "https://[fd00:ec2::254]/v1",
    "https://[::ffff:127.0.0.1]/v1",
    "https://[::ffff:169.254.169.254]/v1",
    "https://[64:ff9b::7f00:1]/v1",
    "https://2130706433/v1",          # 127.0.0.1 en decimal
    "https://0x7f000001/v1",          # en hexadecimal
    "https://0177.0.0.1/v1",          # en octal
    "https://127.1/v1",               # forma corta
    "https://0xa9.0xfe.0xa9.0xfe/v1",  # 169.254.169.254 por bytes en hexadecimal
    "https://metadata.google.internal/v1",
    "https://servicio.internal/v1",
    "https://impresora.local/v1",
    "https://nas.lan/v1",
    "https://router.home.arpa/v1",
    "https://127.0.0.1.nip.io/v1",
    "https://10.0.0.1.sslip.io/v1",
    "https://usuario:clave@api.ejemplo.com/v1",
    "https://api.ejemplo.com@127.0.0.1/v1",
    "https:///v1",
    "https://",
    "api.ejemplo.com/v1",             # sin esquema
    "javascript:alert(1)",
]

METADATOS = [
    "http://169.254.169.254/latest",
    "http://169.254.170.2/v2",
    "http://[fd00:ec2::254]/",
    "http://metadata.google.internal/computeMetadata/v1",
    "http://100.100.100.200/latest",
    "http://2852039166/",             # 169.254.169.254 en decimal
    "http://[::ffff:a9fe:a9fe]/",
]

PRIVADAS_ON_PREM = [
    "http://engine:4000/v1",
    "http://ollama:11434/v1",
    "http://10.0.0.5:8000/v1",
    "https://192.168.1.10/v1",
    "http://127.0.0.1:8000/v1",
    "https://modelos.empresa.internal/v1",
    "http://localhost:11434",
]


def _compose_services():
    nombres = set()
    for ruta in ("docker-compose.yml", "deploy/docker/compose.prod.yml"):
        data = yaml.safe_load((ROOT / ruta).read_text(encoding="utf-8"))
        nombres |= set((data.get("services") or {}))
    return sorted(nombres)


@pytest.fixture(autouse=True)
def _sin_interruptor(monkeypatch):
    monkeypatch.delenv(ab.ALLOW_PRIVATE_ENV, raising=False)


@pytest.mark.parametrize("url", PUBLICAS)
def test_una_direccion_publica_https_se_acepta(url):
    assert ab.check_api_base(url) == url.strip()


@pytest.mark.parametrize("url", INTERNAS)
def test_una_empresa_no_apunta_a_la_red_interna(url):
    with pytest.raises(ab.ApiBaseError):
        ab.check_api_base(url)


@pytest.mark.parametrize("servicio", _compose_services())
def test_los_nombres_de_servicio_de_los_compose_se_rechazan(servicio):
    for url in (f"http://{servicio}:4000/v1", f"https://{servicio}/v1", f"https://{servicio.upper()}:8443"):
        with pytest.raises(ab.ApiBaseError):
            ab.check_api_base(url)


def test_los_servicios_de_los_compose_se_leyeron():
    assert {"engine", "db", "backend"} <= set(_compose_services())


def test_los_mensajes_son_neutros_y_no_nombran_componentes_internos():
    mensajes = []
    for url in INTERNAS + [f"http://{s}:1/" for s in _compose_services()]:
        with pytest.raises(ab.ApiBaseError) as exc:
            ab.check_api_base(url)
        mensajes.append(str(exc.value).lower())
    texto = " ".join(mensajes)
    for prohibido in ("engine", "litellm", "presidio", "docker", "compose", "169.254", "metadata", "ssrf"):
        assert prohibido not in texto


@pytest.mark.parametrize("valor", ["true", "1", "yes", "on", "TRUE"])
def test_el_interruptor_de_instalacion_permite_privadas_y_http(monkeypatch, valor):
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, valor)
    for url in PRIVADAS_ON_PREM:
        assert ab.check_api_base(url) == url


@pytest.mark.parametrize("valor", ["", "false", "0", "no", "tal vez"])
def test_sin_el_interruptor_o_apagado_rige_la_regla_estricta(monkeypatch, valor):
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, valor)
    for url in PRIVADAS_ON_PREM:
        with pytest.raises(ab.ApiBaseError):
            ab.check_api_base(url)


@pytest.mark.parametrize("url", METADATOS + ["file:///etc/passwd", "ftp://servidor/x", "https://usuario:clave@10.0.0.1/"])
def test_con_el_interruptor_los_metadatos_de_nube_y_file_siguen_rechazados(monkeypatch, url):
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, "true")
    with pytest.raises(ab.ApiBaseError):
        ab.check_api_base(url)


def test_el_argumento_explicito_manda_sobre_el_entorno(monkeypatch):
    monkeypatch.setenv(ab.ALLOW_PRIVATE_ENV, "true")
    with pytest.raises(ab.ApiBaseError):
        ab.check_api_base("http://engine:4000/v1", allow_private=False)
    assert ab.check_api_base("http://engine:4000/v1", allow_private=True)


def test_el_valor_se_normaliza_sin_espacios_exteriores():
    assert ab.check_api_base("  https://api.ejemplo.com/v1  ") == "https://api.ejemplo.com/v1"


def test_vacio_o_ausente_no_es_un_error_de_esta_regla():
    assert ab.check_api_base(None) is None
    assert ab.check_api_base("") is None


def test_la_logica_es_generica_sin_cadenas_de_producto():
    texto = (pathlib.Path(ab.__file__)).read_text(encoding="utf-8").lower()
    for marca in ("elea", "eleia"):
        assert marca not in texto
