"""Listas de referencia del motor para el alta guiada (069 T124; research D27; FR-048..050, FR-057).

El **servidor** (no la consola) lee del motor, por la red interna y sin llave, tres listados públicos:
`/public/providers`, `/public/providers/fields` y `/public/litellm_model_cost_map`. Se guardan en
memoria con TTL de 24 h y recarga manual. Son **sugerencias**: nunca se escriben como verdad.

- Motor caído ⇒ `available: false`, jamás una excepción (alta manual, SC-014). Un fallo no se reintenta
  en cada pedido (`RETRY_AFTER`); si ya había datos, se sirve lo último conocido con `stale: true`.
- El nombre de proveedor del motor se traduce al del catálogo con una tabla EXPLÍCITA
  (`ENGINE_TO_CATALOG`), nunca por heurística; el resto se muestra como no soportado.
- `fetch` y `clock` son inyectables para tests (sin red ni espera).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sentinel.redirect import credentials as rc

from . import models as cm

TTL = 24 * 3600.0
RETRY_AFTER = 30.0
SOURCE = "referencia del motor"
UNSUPPORTED_REASON = "Todavía no se puede servir desde Sentinel"
PATHS = ("/public/providers", "/public/providers/fields", "/public/litellm_model_cost_map")

# Proveedor del motor (id de `/public/providers` o `litellm_provider` del mapa) → proveedor del catálogo.
ENGINE_TO_CATALOG = {
    "openai": "openai", "anthropic": "anthropic", "azure": "azure", "azure_ai": "azure_ai",
    "bedrock": "bedrock", "bedrock_converse": "bedrock", "vertex_ai": "vertex_ai",
    "vertex_ai-language-models": "vertex_ai", "vertex_ai-anthropic_models": "vertex_ai",
    "deepseek": "deepseek", "gemini": "gemini", "groq": "groq", "mistral": "mistral",
    "openrouter": "openrouter", "ollama": "ollama", "hosted_vllm": "hosted_vllm",
    "nvidia_nim": "nvidia_nim", "zai": "zai", "z_ai": "zai",
}
assert set(ENGINE_TO_CATALOG.values()) <= set(cm.PROVIDERS)

_MODE_ROLE = {"chat": "text", "completion": "text", "responses": "text", "embedding": "embeddings",
              "image_generation": "image", "image_edit": "image", "audio_transcription": "audio",
              "audio_speech": "audio", "rerank": "rerank"}
_FEATURE_FLAGS = {"supports_vision": "images", "supports_pdf_input": "documents_pdf",
                  "supports_function_calling": "tools", "supports_reasoning": "thinking",
                  "supports_prompt_caching": "cache_control"}

Fetch = Callable[[str], Any]


def engine_base() -> str:
    return (os.environ.get("SENTINEL_ENGINE_API_BASE") or "http://engine:4000").rstrip("/")


def _http_fetch(path: str) -> Any:
    import httpx
    r = httpx.get(engine_base() + path, timeout=20.0)
    r.raise_for_status()
    return r.json()


def role_of_mode(mode: Optional[str]) -> Optional[str]:
    """`mode` del motor → `role` del catálogo; `None` si el catálogo no sirve ese tipo (moderación…)."""
    return _MODE_ROLE.get(mode or "")


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v) -> Optional[int]:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _credential_fields(provider: str, engine_fields: list) -> list:
    """Campos de credencial en la forma del catálogo (`rc.SHAPES`): se conserva la etiqueta del motor
    cuando la clave coincide; la obligatoriedad la manda el catálogo; lo que el catálogo no usa
    (p. ej. `api_base`, que es un campo de la entrada) se descarta."""
    required, optional = rc.SHAPES[provider]
    labels = {f.get("key"): f for f in engine_fields if isinstance(f, dict)}
    out = []
    for key in sorted(required) + sorted(optional):
        src = labels.get(key) or {}
        out.append({"key": key, "label": src.get("label") or key, "required": key in required,
                    "field_type": src.get("field_type") or ("password" if "key" in key or "secret" in key
                                                             or "credentials" in key else "text")})
    return out


def _provider_item(provider: str, display: str, fields: list, example: Optional[str]) -> dict:
    return {"provider": provider, "display_name": display, "supported": True,
            "credential_fields": _credential_fields(provider, fields),
            "requires_api_base": rc.requires_api_base(provider),
            "default_api_base": rc.DEFAULT_API_BASE.get(provider), "example_model": example}


class Reference:
    def __init__(self, fetch: Optional[Fetch] = None, clock: Callable[[], float] = time.time,
                 ttl: float = TTL):
        self._fetch, self._clock, self._ttl = fetch or _http_fetch, clock, ttl
        self._lock = threading.Lock()
        self._snap: Optional[dict] = None
        self._at = 0.0
        self._failed_at: Optional[float] = None

    # ── carga ──
    def _load(self, force: bool = False) -> Optional[dict]:
        """La instantánea vigente, o `None` si el motor no responde y no hay nada que servir."""
        with self._lock:
            now = self._clock()
            fresh = self._snap is not None and now - self._at < self._ttl
            if fresh and not force:
                return self._snap
            if not force and self._failed_at is not None and now - self._failed_at < RETRY_AFTER:
                return self._snap
            try:
                provs, fields, cost = (self._fetch(p) for p in PATHS)
                if not isinstance(provs, list) or not isinstance(fields, list) or not isinstance(cost, dict):
                    raise ValueError("respuesta inesperada del motor")
            except Exception:  # noqa: BLE001 — motor caído o lista malformada: sin excepción hacia arriba
                self._failed_at = now
                if self._snap is not None:
                    self._snap = {**self._snap, "stale": True}
                return self._snap
            self._snap = self._build(provs, fields, cost, now)
            self._at, self._failed_at = now, None
            return self._snap

    def refresh(self) -> bool:
        return self._load(force=True) is not None and not self._snap.get("stale")

    def _build(self, provs: list, fields: list, cost: dict, now: float) -> dict:
        by_id = {f.get("provider"): f for f in fields if isinstance(f, dict)}
        items, seen = [], set()
        for pid in provs:
            if not isinstance(pid, str):
                continue
            f = by_id.get(pid) or {}
            display = f.get("provider_display_name") or pid
            cat = ENGINE_TO_CATALOG.get(pid)
            if cat is None:
                items.append({"provider": pid, "display_name": display, "supported": False,
                              "reason": UNSUPPORTED_REASON, "credential_fields": [],
                              "example_model": f.get("default_model_placeholder")})
            elif cat not in seen:
                seen.add(cat)
                items.append(_provider_item(cat, display, f.get("credential_fields") or [],
                                            f.get("default_model_placeholder")))
        for cat in cm.PROVIDERS:        # lo que el catálogo sirve y el motor no lista: alta manual igual
            if cat not in seen:
                seen.add(cat)
                items.append(_provider_item(cat, cat, [], None))
        items.sort(key=lambda p: (not p["supported"], p["display_name"].lower()))
        models: dict = {}
        for name, spec in cost.items():
            if name == "sample_spec" or not isinstance(spec, dict):
                continue
            cat = ENGINE_TO_CATALOG.get(spec.get("litellm_provider"))
            role = role_of_mode(spec.get("mode"))
            if cat is None or role is None:
                continue
            models.setdefault(cat, {})[self._real_name(name, cat, spec)] = self._model(
                self._real_name(name, cat, spec), role, spec)
        for cat in models:
            models[cat] = dict(sorted(models[cat].items()))
        return {"fetched_at": _iso(now), "providers": items, "models": models}

    @staticmethod
    def _real_name(key: str, cat: str, spec: dict) -> str:
        head, sep, rest = key.partition("/")
        prefixes = {cat, spec.get("litellm_provider")} | {k for k, v in ENGINE_TO_CATALOG.items() if v == cat}
        return rest if sep and head in prefixes else key

    @staticmethod
    def _model(real: str, role: str, spec: dict) -> dict:
        return {
            "real_model": real, "role": role, "mode": spec.get("mode"),
            "context_window": _int(spec.get("max_input_tokens")) or _int(spec.get("max_tokens")),
            "max_output": _int(spec.get("max_output_tokens")),
            "price": {"input": _num(spec.get("input_cost_per_token")),
                      "output": _num(spec.get("output_cost_per_token")),
                      "cache_read": _num(spec.get("cache_read_input_token_cost")),
                      "cache_write": _num(spec.get("cache_creation_input_token_cost"))},
            "features": {feat: True for flag, feat in _FEATURE_FLAGS.items() if spec.get(flag) is True},
        }

    # ── lecturas ──
    def providers(self) -> dict:
        snap = self._load()
        if snap is None:
            return {"available": False, "fetched_at": None,
                    "data": [_provider_item(p, p, [], None) for p in cm.PROVIDERS]}
        out = {"available": True, "fetched_at": snap["fetched_at"], "data": list(snap["providers"])}
        if snap.get("stale"):
            out["stale"] = True
        return out

    def models(self, provider: str, q: str = "", limit: int = 50, offset: int = 0) -> dict:
        snap = self._load()
        if snap is None:
            return {"available": False, "fetched_at": None, "total": 0, "data": []}
        rows = list(snap["models"].get(provider, {}).values())
        if q:
            rows = [m for m in rows if q.lower() in m["real_model"].lower()]
        out = {"available": True, "fetched_at": snap["fetched_at"], "total": len(rows),
               "data": rows[max(offset, 0):max(offset, 0) + max(limit, 0)]}
        if snap.get("stale"):
            out["stale"] = True
        return out

    def model(self, provider: str, real_model: str) -> Optional[dict]:
        snap = self._load()
        return None if snap is None else snap["models"].get(provider, {}).get(real_model)


# Instancia del proceso; los tests la reemplazan (`api/reference.py: REFERENCE`).
_default: Optional[Reference] = None


def default() -> Reference:
    global _default
    if _default is None:
        _default = Reference()
    return _default
