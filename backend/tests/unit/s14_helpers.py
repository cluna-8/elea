"""Ayudas compartidas de los tests de S14 (alcance completo del enmascarado forzado, 057).

- Doble mínimo de `litellm.integrations.custom_guardrail` (la suite del backend no trae el motor).
- PDFs **generados en el test**, a mano (sin `pypdf` para crearlos, sin binarios versionados): con
  texto, sin texto, bomba de compresión y páginas densas.
- `analizador(region)`: el detector regex de la base (`default_analyze`) con la región fijada, para
  no depender del sidecar NLP.
"""
import base64
import importlib.util
import sys
import types
import zlib
from functools import partial


def instalar_doble_litellm():
    if "litellm.integrations.custom_guardrail" in sys.modules:
        return

    class CustomGuardrail:
        def __init__(self, *args, **kwargs):
            pass

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    integrations = sys.modules.setdefault(
        "litellm.integrations", types.ModuleType("litellm.integrations"))
    modulo = types.ModuleType("litellm.integrations.custom_guardrail")
    modulo.CustomGuardrail = CustomGuardrail
    sys.modules["litellm.integrations.custom_guardrail"] = modulo
    litellm_mod.integrations = integrations
    integrations.custom_guardrail = modulo


instalar_doble_litellm()

from extensions import sentinel_guardian_policy as policy  # noqa: E402

HAY_PYPDF = importlib.util.find_spec("pypdf") is not None

DNI = "30123456"
DNI_PUNTOS = "30.123.456"
CUIT = "20-30123456-7"
CUIT_SIN_GUIONES = "20301234567"
CBU = "2850590940090418135201"


def analizador(region: str = "latam_ar"):
    return partial(policy.default_analyze, region=region)


def kind_esperado(kind: str) -> str:
    """Con `pypdf` el nombre de tipo del contrato; sin `pypdf` (imagen base del motor) todo PDF
    es no analizable con el mismo nombre: la rama «sin `pypdf` ⇒ no analizable» se verifica en
    el mismo archivo, sin saltear."""
    return kind if HAY_PYPDF else "pdf_unavailable"


# ── PDFs a mano ────────────────────────────────────────────────────────────────────

def _armar_pdf(contenidos: list, *, extra_stream_dict: str = "") -> bytes:
    """PDF mínimo válido: un objeto de contenido por página (los `bytes` ya van como flujo)."""
    objs = []                                   # lista de bytes del cuerpo de cada objeto
    n_pages = len(contenidos)
    # 1 catálogo, 2 páginas, 3 fuente, luego (página, contenido) por página
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, flujo in enumerate(contenidos):
        pagina = 4 + 2 * i
        objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                     f"/Resources << /Font << /F1 3 0 R >> >> /Contents {pagina + 1} 0 R >>").encode())
        cuerpo, dic = flujo
        objs.append(f"<< /Length {len(cuerpo)} {dic} {extra_stream_dict} >>\nstream\n".encode()
                    + cuerpo + b"\nendstream")
    salida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, cuerpo in enumerate(objs, start=1):
        offsets.append(len(salida))
        salida += f"{num} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        salida += f"{off:010d} 00000 n \n".encode()
    salida += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(salida)


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_con_texto(*paginas: str) -> bytes:
    """PDF con una línea de texto por página (solo ASCII/Latin-1 simple)."""
    flujos = []
    for texto in paginas:
        flujo = f"BT /F1 12 Tf 72 720 Td ({_escapar(texto)}) Tj ET".encode("latin-1")
        flujos.append((flujo, ""))
    return _armar_pdf(flujos)


def pdf_sin_texto(n_paginas: int = 1) -> bytes:
    """Como un escaneado: páginas con un dibujo (un rectángulo) y ningún operador de texto."""
    return _armar_pdf([(b"0 0 100 100 re f", "") for _ in range(n_paginas)])


def pdf_bomba_de_compresion(expandido: int = 60_000_000) -> bytes:
    """Un PDF chico cuyo flujo `FlateDecode` se expande a `expandido` bytes (espacios)."""
    flujo = zlib.compress(b" " * expandido, 9)
    return _armar_pdf([(flujo, "/Filter /FlateDecode")])


def pdf_paginas_densas(paginas: int = 4, operadores: int = 60_000) -> bytes:
    """Dentro del tope de páginas y de bytes, pero con decenas de miles de operadores de texto por
    página: el trabajo del parser es el costo, no el tamaño."""
    cuerpo = ("BT /F1 8 Tf 10 10 Td (x) Tj ET\n" * operadores).encode()
    return _armar_pdf([(zlib.compress(cuerpo, 9), "/Filter /FlateDecode")
                       for _ in range(paginas)])


def pdf_protegido() -> bytes:
    """PDF cifrado (requiere `pypdf` para armarlo; sin `pypdf` cualquier PDF ya es no analizable)."""
    if not HAY_PYPDF:
        return pdf_con_texto("cifrado")
    import io

    from pypdf import PdfReader, PdfWriter
    escritor = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_con_texto("cifrado"))))
    escritor.encrypt("clave-de-prueba")
    destino = io.BytesIO()
    escritor.write(destino)
    return destino.getvalue()


def b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def bloque_pdf(datos: bytes) -> dict:
    """Bloque `document` de Anthropic con el PDF en base64."""
    return {"type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64(datos)}}


def parte_pdf_openai(datos: bytes) -> dict:
    return {"type": "file",
            "file": {"filename": "doc.pdf",
                     "file_data": f"data:application/pdf;base64,{b64(datos)}"}}
