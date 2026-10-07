"""Kits de cliente por herramienta y alcance (contracts/kits.md; FR-030, FR-035; T110).

Función pura: del catálogo publicado del alcance y la dirección de la pasarela salen los archivos
de configuración de cada herramienta. Sin credencial, salvo que el llamador pase `api_key` — la
llave NUEVA que la ruta emitió para ese alcance (nunca credenciales de destino) —; sin ella cada
archivo lleva un marcador a reemplazar.

Marca (FR-035): ningún identificador del fabricante ni del motor. Los únicos nombres de terceros
son los que la herramienta exige literalmente (`ANTHROPIC_*`, `OPENAI_*`, claves de config de
Claude Desktop, `wire_api`…). `brand` es el nombre visible de la instalación; el proveedor de
Codex se nombra con ella — nunca con el del fabricante, para evitar la compactación remota.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Iterable, Mapping, Optional

TOOLS = ("claude_desktop", "claude_code", "codex", "openai_generic")
TOOL_FACE = {"claude_desktop": "claude", "claude_code": "claude", "codex": "codex",
             "openai_generic": "openai_generic"}
KEY_PLACEHOLDER = "REEMPLAZAR_CON_LA_LLAVE_DE_LA_CONEXION"
URL_PLACEHOLDER = "REEMPLAZAR_CON_LA_URL_DE_LA_PASARELA"
# Tope (rpm, tpm) con el que nace la llave que emite el kit. Cada pedido de Claude Desktop/Cowork pesa 35 000–67 000
# tokens: con el default de la base (60 / 100 000) el segundo pedido del minuto ya lo excede. Las demás herramientas
# conservan el default de la base (no figuran acá).
KEY_LIMITS = {"claude_desktop": (120, 1_000_000), "claude_code": (120, 1_000_000)}
CLAUDE_TIERS = ("opus", "sonnet", "haiku", "fable")
STREAM_IDLE_SEC = 600


class KitError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def brand_slug(brand: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", brand or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "gateway"


def min_context_window(published: Iterable[Mapping[str, Any]], rules: Iterable[Mapping[str, Any]],
                       destinations: Mapping[str, Mapping[str, Any]]) -> Optional[int]:
    """Ventana más chica entre los destinos de las reglas que sirven a estos ids (la herramienta
    compacta contra ella: pasarse es el fallo conocido de contexto excedido)."""
    published = list(published)
    ids = {str(p.get("id")) for p in published if p.get("id") is not None}
    tiers = {p.get("family_tier") for p in published if p.get("family_tier")}
    windows = []
    for rule in rules:
        by_id = rule.get("published_model_id") is not None and str(rule["published_model_id"]) in ids
        by_tier = rule.get("published_model_id") is None and rule.get("family_tier") in tiers
        if not (by_id or by_tier):
            continue
        for target in rule.get("targets") or ():
            window = (destinations.get(str(target)) or {}).get("context_window")
            if window:
                windows.append(int(window))
    return min(windows) if windows else None


def _pick_default(rows: list) -> Mapping[str, Any]:
    return next((r for r in rows if r.get("is_family_default")), rows[0])


def _file(path: str, content: str, **extra) -> dict:
    return {"path": path, "content": content if content.endswith("\n") else content + "\n", **extra}


def _claude_desktop(ctx) -> dict:
    models = [{"name": p["public_id"], "labelOverride": p.get("label") or p["public_id"],
               "anthropicFamilyTier": p.get("family_tier") or "sonnet",
               "isFamilyDefault": bool(p.get("is_family_default")), "supports1m": False,
               "maxEffort": "high"} for p in ctx.rows]
    cfg = {"inferenceProvider": "gateway", "inferenceGatewayBaseUrl": ctx.gw,
           "inferenceGatewayApiKey": ctx.key, "inferenceGatewayAuthScheme": "bearer",
           "inferenceModels": models, "inferenceStreamIdleTimeoutSec": STREAM_IDLE_SEC,
           "skipWebFetchPreflight": True}
    howto = (f"Configuración gestionada de {ctx.brand} para Claude Desktop.\n"
             "Copiar managed-settings.json a /etc/claude-desktop/managed-settings.json "
             "(propietario root, permisos 0644) o repartirlo con la gestión de dispositivos.\n")
    return {"files": [_file("managed-settings.json", json.dumps(cfg, indent=2, ensure_ascii=False),
                            install_path="/etc/claude-desktop/managed-settings.json"),
                      _file("LEEME.txt", howto)],
            "notes": ["Un id publicado por cada modelo que verá la herramienta."]}


def _claude_code(ctx) -> dict:
    by_tier = {t: [p for p in ctx.rows if p.get("family_tier") == t] for t in CLAUDE_TIERS}
    lines = [f"# Claude Code contra {ctx.brand}. Cargar en el entorno o en el archivo de ajustes.",
             "# Con sesión de suscripción en la máquina, usar un directorio de configuración "
             "aislado: CLAUDE_CONFIG_DIR=<ruta>",
             f"ANTHROPIC_BASE_URL={ctx.gw}", f"ANTHROPIC_AUTH_TOKEN={ctx.key}"]
    for tier in CLAUDE_TIERS:
        if by_tier[tier]:
            lines.append(f"ANTHROPIC_DEFAULT_{tier.upper()}_MODEL={_pick_default(by_tier[tier])['public_id']}")
    if ctx.window:
        lines.append(f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={ctx.window}")
    lines += ["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1", "CLAUDE_CODE_GATEWAY_HINT_HEADERS=1",
              "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1"]
    return {"files": [_file("claude-code.env", "\n".join(lines))],
            "notes": ["Si la máquina tiene sesión de suscripción, usar un directorio de "
                      "configuración aislado."]}


def _codex(ctx) -> dict:
    default = _pick_default(ctx.rows)["public_id"]
    slug = ctx.slug
    config = "\n".join([
        f"# Codex contra {ctx.brand}. Definir antes de usarlo: GATEWAY_API_KEY={ctx.key}",
        f'model = "{default}"', f'model_provider = "{slug}"',
        f'model_catalog_json = "~/.codex/{slug}-models.json"', 'forced_login_method = "api"', "",
        f"[model_providers.{slug}]", f'name = "{ctx.brand}"', f'base_url = "{ctx.gw}/v1"',
        'env_key = "GATEWAY_API_KEY"', 'wire_api = "responses"', "supports_websockets = false",
        f"stream_idle_timeout_ms = {STREAM_IDLE_SEC * 1000}", "", "[analytics]", "enabled = false"])
    catalog = {"models": [{"slug": p["public_id"], "display_name": p.get("label") or p["public_id"],
                           "context_window": ctx.window, "use_responses_lite": False,
                           "apply_patch_tool_type": "freeform", "supports_parallel_tool_calls": False}
                          for p in ctx.rows]}
    return {"files": [_file("~/.codex/config.toml", config),
                      _file(f"~/.codex/{slug}-models.json", json.dumps(catalog, indent=2, ensure_ascii=False)),
                      _file("/etc/codex/requirements.toml", 'allowed_login_methods = ["api"]')],
            "notes": ["El proveedor lleva el nombre de la instalación; la clave va por variable de entorno."]}


def _openai_generic(ctx) -> dict:
    aliases = ", ".join(p["public_id"] for p in ctx.rows)
    lines = [f"# Cliente compatible con la API genérica de {ctx.brand} (opencode, Aider, Continue, Cline, Zed…)",
             f"OPENAI_BASE_URL={ctx.gw}/v1", f"OPENAI_API_KEY={ctx.key}",
             f"# modelos disponibles: {aliases}"]
    return {"files": [_file("openai.env", "\n".join(lines))], "notes": []}


_BUILDERS = {"claude_desktop": _claude_desktop, "claude_code": _claude_code, "codex": _codex,
             "openai_generic": _openai_generic}


class _Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def build_kit(tool: str, *, gateway_url: str, brand: str, published: Iterable[Mapping[str, Any]],
              context_window: Optional[int] = None, api_key: Optional[str] = None) -> dict:
    if tool not in _BUILDERS:
        raise KitError("unknown_tool", f"herramienta desconocida: {tool}")
    face = TOOL_FACE[tool]
    rows = sorted((p for p in published if p.get("face") == face), key=lambda p: p["public_id"])
    if not rows:
        raise KitError("no_models", "no hay modelos publicados para esta herramienta en el alcance")
    ctx = _Ctx(gw=gateway_url.rstrip("/"), brand=brand or "Gateway", slug=brand_slug(brand), rows=rows,
               window=context_window, key=api_key or KEY_PLACEHOLDER)
    out = _BUILDERS[tool](ctx)
    return {"tool": tool, "face": face, "uses_credential": bool(api_key),
            "models": [p["public_id"] for p in rows], **out}
