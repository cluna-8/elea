"""Esquema de material de virtual keys — compartido (reuse over reinvent, FR-025).

Única fuente del hash y el preview de las keys: lo usan el flujo online
(``api/keys.py``) y el onboarding-as-data (``services/onboarding.py``). En DB solo
se persiste el hash sha256; la key en claro se muestra una única vez al emitirla.
"""
import hashlib


def hash_key(plain_key: str) -> str:
    return hashlib.sha256(plain_key.encode()).hexdigest()


def key_preview(plain_key: str) -> str:
    return f"sk-...{plain_key[-6:]}"
