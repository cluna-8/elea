"""Validación de la `api_base` de las entradas de empresa (057 H1; Constitución III y Seguridad 4).

El motor llama a la `api_base` de una entrada con la credencial de esa entrada. Si el administrador de una empresa
pudiera cargar cualquier dirección, el motor compartido alcanzaría la red interna de la instalación o los metadatos
de la nube (un SSRF). Una entrada de **empresa** exige entonces:

- esquema `https`, sin usuario ni contraseña en la dirección;
- un host público: ni literales de IP de loopback, link-local, privadas, CGNAT, no especificadas, multicast o
  reservadas (en decimal, hexadecimal, octal, forma corta o IPv6 con IPv4 incrustada), ni `localhost`, ni nombres
  sin punto (los servicios de la red de contenedores), ni sufijos de red interna, ni DNS comodín que resuelve a IP.

El interruptor de **instalación** `CATALOG_ALLOW_PRIVATE_API_BASE` (apagado por defecto) permite http y direcciones
privadas para modelos locales on-prem de una instalación de un solo tenant; nunca los metadatos de nube ni esquemas
que no sean http(s). Las entradas de instalación (las carga el operador) no pasan por esta regla.

Los mensajes son neutros: no nombran componentes internos ni explican qué rango se tocó.
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Optional
from urllib.parse import urlsplit

ALLOW_PRIVATE_ENV = "CATALOG_ALLOW_PRIVATE_API_BASE"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_MSG = "api_base no válida: tiene que ser una dirección https de un host público del proveedor"
_MSG_ON_PREM = "api_base no válida: tiene que ser una dirección http o https de un host del proveedor"

# Metadatos de nube: nunca, ni con el interruptor.
_METADATA_HOSTS = frozenset({"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal",
                             "metadata.goog", "metadata.azure.internal"})
_METADATA_NETS = tuple(ipaddress.ip_network(n) for n in (
    "169.254.0.0/16",          # link-local IPv4 (incluye 169.254.169.254 y 169.254.170.2)
    "100.100.100.200/32",      # metadatos de otra nube
    "fe80::/10",               # link-local IPv6
    "fd00:ec2::/32",           # metadatos IPv6 de una nube
))
# Nombres que no son hosts públicos: sufijos de red interna y DNS comodín que resuelven a una IP elegida.
_INTERNAL_SUFFIXES = (".localhost", ".internal", ".local", ".localdomain", ".lan", ".home.arpa", ".intranet",
                      ".corp", ".private", ".in-addr.arpa", ".ip6.arpa")
_WILDCARD_DNS = ("nip.io", "sslip.io", "xip.io", "localtest.me", "lvh.me", "traefik.me")
_NUMERIC_TOKEN = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class ApiBaseError(ValueError):
    """La `api_base` no es una dirección permitida para una entrada de empresa."""


def private_allowed() -> bool:
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower() in _TRUTHY


def _loose_ipv4(host: str) -> Optional[ipaddress.IPv4Address]:
    """IPv4 como la interpreta `inet_aton` (decimal, hexadecimal, octal, forma corta); `None` si no es numérica."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or not all(_NUMERIC_TOKEN.match(p) for p in parts):
        return None
    nums = []
    for p in parts:
        try:
            nums.append(int(p, 16) if p.startswith("0x") else int(p, 8) if len(p) > 1 and p.startswith("0")
                        else int(p, 10))
        except ValueError:
            raise ApiBaseError(_MSG) from None       # `0x` sin dígitos, `09`…: no es una dirección legítima
    *head, last = nums
    if any(n > 255 for n in head) or last >= 256 ** (4 - len(head)):
        raise ApiBaseError(_MSG)
    value = last
    for i, n in enumerate(head):
        value += n << (8 * (3 - i))
    return ipaddress.IPv4Address(value)


def _ip_of(host: str):
    """`ipaddress` del host si es un literal de IP (en cualquier representación); `None` si es un nombre."""
    if ":" in host:
        if "%" in host:
            raise ApiBaseError(_MSG)
        try:
            return ipaddress.IPv6Address(host)
        except ValueError:
            raise ApiBaseError(_MSG) from None
    return _loose_ipv4(host)


def _embedded_v4(ip):
    """La IPv4 que una IPv6 lleva dentro (mapeada `::ffff:a.b.c.d` o NAT64 `64:ff9b::/96`), si la lleva."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _is_metadata(ip) -> bool:
    return any(ip in n for n in _METADATA_NETS if n.version == ip.version)


def _is_non_public(ip) -> bool:
    return (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local
            or ip.is_unspecified or ip.is_private)


def check_api_base(value: Optional[str], *, allow_private: Optional[bool] = None) -> Optional[str]:
    """Devuelve la `api_base` sin espacios exteriores o levanta `ApiBaseError`. Vacía o ausente ⇒ `None`
    (que exista es otra regla, la de cada proveedor). `allow_private` por defecto lee el interruptor de instalación."""
    if value is None or not str(value).strip():
        return None
    permissive = private_allowed() if allow_private is None else allow_private
    msg = _MSG_ON_PREM if permissive else _MSG
    raw = str(value).strip()
    try:
        parts = urlsplit(raw)
        host, _port = parts.hostname, parts.port           # `.port` valida el puerto
    except ValueError:
        raise ApiBaseError(msg) from None
    scheme = (parts.scheme or "").lower()
    if scheme not in (("https", "http") if permissive else ("https",)) or not host:
        raise ApiBaseError(msg)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ApiBaseError(msg)
    host = host.rstrip(".").lower()
    if not host or any(ord(c) < 33 or ord(c) > 126 for c in host):
        raise ApiBaseError(msg)
    ip = _ip_of(host)
    if ip is not None:
        for candidate in (ip, _embedded_v4(ip)):
            if candidate is None:
                continue
            if _is_metadata(candidate):
                raise ApiBaseError(msg)
            if not permissive and _is_non_public(candidate):
                raise ApiBaseError(msg)
        if permissive and (ip.is_multicast or ip.is_unspecified):
            raise ApiBaseError(msg)
        return raw
    if host in _METADATA_HOSTS or host.endswith(".metadata.google.internal"):
        raise ApiBaseError(msg)
    if permissive:
        return raw
    if "." not in host or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        raise ApiBaseError(msg)
    if any(host == d or host.endswith("." + d) for d in _WILDCARD_DNS):
        raise ApiBaseError(msg)
    return raw
